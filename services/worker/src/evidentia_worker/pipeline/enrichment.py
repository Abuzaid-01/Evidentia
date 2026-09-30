"""DEDUP_CHECKED -> ANALYZING -> INDEXED: AI enrichment.

Order (cheap and Cloudinary-native first, then the structured extraction chain):
  1. Cloudinary Analyze API: captioning, image_quality, ai_vision_tagging (project taxonomy)
  2. Structured extraction chain: Cloudinary AI Vision -> Gemini -> Groq (first valid answer wins)
  3. OCR add-on, only when the extraction says readable text is present
  4. Auto-tagging add-on, when enabled

Videos take a different path (`pipeline.video`): timestamped segments from Cloudinary AI Video
Analysis, or keyframes when that Beta API is off. Images stay on the path below.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import structlog
from evidentia_ai.chain import run_chain
from evidentia_ai.normalize import (
    auto_tag_drafts,
    caption_draft,
    from_extraction,
    ocr_draft,
    quality_draft,
    tagging_drafts,
)
from evidentia_ai.prompts import PROMPT_VERSION, AnalysisContext, extraction_prompt, prompt_hash
from evidentia_ai.providers import ImageInput
from evidentia_ai.schemas import SCHEMA_VERSION, VisionExtraction
from evidentia_cloudinary import admin
from evidentia_cloudinary.analyze import (
    MAX_TAG_DEFINITIONS,
    caption_text,
    cloudinary_tag_name,
    source_uri,
    tagged_names,
)
from evidentia_cloudinary.delivery import rendition_url
from evidentia_cloudinary.errors import CloudinaryPermanentError
from evidentia_core.db.models import Asset, Derivative, Project, Site, Taxonomy
from evidentia_core.domain.enums import AnalysisTask, AssetState, ResourceType
from evidentia_core.domain.taxonomy import Activity
from sqlalchemy import select
from sqlalchemy.orm import Session

from evidentia_worker.context import WorkerContext
from evidentia_worker.errors import PermanentError, RetryableError
from evidentia_worker.pipeline import runs
from evidentia_worker.pipeline.indexing import index_asset
from evidentia_worker.pipeline.runs import PermanentRunFailure, RunOutput, RunSpec
from evidentia_worker.pipeline.state import transition

log = structlog.get_logger("evidentia.enrichment")
MAX_MODEL_IMAGE_BYTES = 15 * 1024 * 1024


def _load_taxonomy(session: Session, project: Project) -> tuple[list[Activity], int]:
    taxonomy = session.scalar(
        select(Taxonomy).where(
            Taxonomy.project_id == project.id, Taxonomy.version == project.active_taxonomy_version
        )
    )
    if taxonomy is None:
        return [], 0
    return [Activity.model_validate(a) for a in taxonomy.activities], taxonomy.version


def model_input(session: Session, asset: Asset, ctx: WorkerContext) -> ImageInput:
    """Fetch the `ai` rendition (bounded JPEG) and record it as a derivative for lineage."""
    rendition = rendition_url(
        asset.public_id, asset.resource_type.value, "ai", use_named=ctx.use_named
    )
    try:
        response = ctx.http.get(rendition.url)
    except httpx.TransportError as exc:
        raise RetryableError(f"model input download failed: {exc}") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableError(f"model input download: HTTP {response.status_code}")
    if response.status_code >= 400:
        raise PermanentError(
            f"model input rendition: HTTP {response.status_code} "
            "(run `make cloudinary-bootstrap` so the named transformations exist)"
        )
    if len(response.content) > MAX_MODEL_IMAGE_BYTES:
        raise PermanentError("model input rendition is unexpectedly large")

    already = session.scalar(
        select(Derivative.id).where(
            Derivative.asset_id == asset.id,
            Derivative.purpose == "ai",
            Derivative.transformation == rendition.transformation,
        )
    )
    if already is None:
        session.add(
            Derivative(
                organization_id=asset.organization_id,
                asset_id=asset.id,
                purpose="ai",
                named_transformation=rendition.named_transformation,
                transformation=rendition.transformation,
                format=rendition.format,
                source="on_demand",
                bytes=len(response.content),
            )
        )
        session.commit()
    return ImageInput(data=response.content, mime_type="image/jpeg", cloudinary_url=rendition.url)


def _cloudinary_native(
    session: Session,
    asset: Asset,
    ctx: WorkerContext,
    image: ImageInput,
    activities: list[Activity],
    taxonomy_version: int,
) -> None:
    client = ctx.analyze
    if client is None or not image.cloudinary_url:
        return
    source = source_uri(image.cloudinary_url)

    def guarded(call):  # type: ignore[no-untyped-def]
        try:
            return call()
        except CloudinaryPermanentError as exc:  # e.g. add-on not enabled on this account
            raise PermanentRunFailure(str(exc)) from exc

    def caption() -> RunOutput:
        result = guarded(lambda: client.captioning(source))
        text = caption_text(result)
        return RunOutput(
            drafts=[caption_draft(text, "cloudinary_captioning")] if text else [],
            raw=result.raw.get("data", {}),
            latency_ms=result.latency_ms,
            model_version=result.model_version,
            usage={"quota": result.quota},
        )

    runs.execute(session, asset, RunSpec(AnalysisTask.CAPTION, "cloudinary", "captioning"), caption)

    if asset.resource_type == ResourceType.IMAGE:

        def quality() -> RunOutput:
            result = guarded(lambda: client.image_quality(source))
            return RunOutput(
                drafts=[quality_draft(result.analysis)],
                raw=result.raw.get("data", {}),
                latency_ms=result.latency_ms,
                model_version=result.model_version,
            )

        runs.execute(
            session, asset, RunSpec(AnalysisTask.QUALITY, "cloudinary", "image_quality"), quality
        )

    # Taxonomy questions -> AI Vision tagging, in batches of at most 10 definitions.
    for start in range(0, len(activities), MAX_TAG_DEFINITIONS):
        batch = activities[start : start + MAX_TAG_DEFINITIONS]
        definitions = [
            {"name": cloudinary_tag_name(a.key), "description": a.question} for a in batch
        ]
        to_key = {cloudinary_tag_name(a.key): a.key for a in batch}  # back to taxonomy keys

        def tagging(
            defs: list[dict[str, str]] = definitions, keys: dict[str, str] = to_key
        ) -> RunOutput:
            result = guarded(lambda: client.ai_vision_tagging(source, defs))
            return RunOutput(
                drafts=tagging_drafts([keys.get(n, n) for n in tagged_names(result)]),
                raw=result.raw.get("data", {}),
                latency_ms=result.latency_ms,
                model_version=result.model_version,
            )

        runs.execute(
            session,
            asset,
            RunSpec(
                AnalysisTask.TAGGING,
                "cloudinary",
                "ai_vision_tagging",
                taxonomy_version=taxonomy_version,
                extra_key=f"batch{start}",
                input={"tag_definitions": definitions},
            ),
            tagging,
        )


def _structured_extraction(
    session: Session,
    asset: Asset,
    ctx: WorkerContext,
    image: ImageInput,
    analysis_ctx: AnalysisContext,
    taxonomy_version: int,
    frame_offset: str | None,
) -> VisionExtraction | None:
    prompt = extraction_prompt(analysis_ctx)
    spec = RunSpec(
        AnalysisTask.VISION_EXTRACT,
        provider="chain",
        model="chain",
        prompt_version=PROMPT_VERSION,
        prompt_hash=prompt_hash(prompt),
        schema_version=SCHEMA_VERSION,
        taxonomy_version=taxonomy_version,
        input={"providers": [p.name for p in ctx.providers], "frame_offset": frame_offset},
    )
    if not ctx.providers:
        log.warning("no_vision_providers_configured", asset_id=str(asset.id))
        return None

    def extract() -> RunOutput:
        outcome = run_chain(ctx.providers, image, analysis_ctx, prompt)
        attempts = [a.__dict__ for a in outcome.attempts]
        if outcome.result is None:
            if outcome.only_transient_failures:
                raise RetryableError(f"all vision providers failed transiently: {attempts}")
            raise PermanentRunFailure(f"no vision provider produced a valid extraction: {attempts}")
        result = outcome.result
        return RunOutput(
            drafts=from_extraction(result.extraction, frame_offset=frame_offset),
            raw={
                "provider": result.provider,
                "extraction": result.extraction.model_dump(),
                "response": result.raw,
                "failed_attempts": attempts,
            },
            latency_ms=result.latency_ms,
            model=result.model,
            provider=result.provider,
            model_version=result.model_version,
            usage=result.usage,
            payload=result.extraction,
        )

    run, output = runs.execute(session, asset, spec, extract)
    if output is not None:
        return output.payload  # type: ignore[no-any-return]
    if run.raw_output and "extraction" in run.raw_output:  # succeeded in an earlier attempt
        return VisionExtraction.model_validate(run.raw_output["extraction"])
    return None


def _addons(
    session: Session, asset: Asset, ctx: WorkerContext, extraction: VisionExtraction | None
) -> None:
    if asset.resource_type != ResourceType.IMAGE:
        return
    settings = ctx.settings

    if settings.cloudinary_ocr_enabled and extraction and extraction.text_present:

        def ocr() -> RunOutput:
            try:
                block = admin.run_ocr(asset.public_id)
            except CloudinaryPermanentError as exc:
                raise PermanentRunFailure(str(exc)) from exc
            text = admin.ocr_full_text(block)
            return RunOutput(
                drafts=[ocr_draft(text)] if text else [], raw={"status": block.get("status")}
            )

        runs.execute(session, asset, RunSpec(AnalysisTask.OCR, "cloudinary", "adv_ocr"), ocr)

    if settings.cloudinary_auto_tagging:
        categorization = settings.cloudinary_auto_tagging

        def auto_tag() -> RunOutput:
            try:
                tags = admin.run_auto_tagging(
                    asset.public_id, categorization, settings.cloudinary_auto_tagging_threshold
                )
            except CloudinaryPermanentError as exc:
                raise PermanentRunFailure(str(exc)) from exc
            return RunOutput(drafts=auto_tag_drafts(tags, categorization), raw={"tags": tags})

        runs.execute(
            session,
            asset,
            RunSpec(AnalysisTask.AUTO_TAGGING, "cloudinary", categorization),
            auto_tag,
        )


def enrich(session: Session, asset: Asset, ctx: WorkerContext) -> None:
    if asset.resource_type == ResourceType.VIDEO:
        from evidentia_worker.pipeline.video import enrich_video

        enrich_video(session, asset, ctx)
        return
    if asset.state == AssetState.DEDUP_CHECKED:
        transition(session, asset, AssetState.ANALYZING, ctx, reason="AI enrichment running")

    project = session.get(Project, asset.project_id)
    assert project is not None
    site = session.get(Site, asset.site_id) if asset.site_id else None
    activities, taxonomy_version = _load_taxonomy(session, project)
    frame_offset = None

    image = model_input(session, asset, ctx)
    _cloudinary_native(session, asset, ctx, image, activities, taxonomy_version)
    analysis_ctx = AnalysisContext(
        project_name=project.name,
        activities=activities,
        site_name=site.name if site else None,
        declared_activity=asset.declared_activity,
        media_kind="video frame" if frame_offset else "photo",
    )
    extraction = _structured_extraction(
        session, asset, ctx, image, analysis_ctx, taxonomy_version, frame_offset
    )
    _addons(session, asset, ctx, extraction)

    flags = dict(asset.flags or {})
    flags["analyzed_at"] = datetime.now(UTC).isoformat()
    flags["vision_extraction"] = extraction is not None
    asset.flags = flags
    index_asset(session, asset, ctx, image=image.data)  # search document + SigLIP embeddings
    transition(session, asset, AssetState.INDEXED, ctx, reason="observations stored + indexed")
