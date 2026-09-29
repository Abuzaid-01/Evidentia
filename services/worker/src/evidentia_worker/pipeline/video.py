"""Video enrichment (Phase 6).

Order, for a video asset only:
  1. Cloudinary AI Video Analysis (Beta) -> timestamped visual observations.
     A pending job raises RetryableError so the worker polls. A permanent failure (add-on off,
     beta unavailable) falls through.
  2. Fallback: a few `so_<t>` frames, each run through the same image extraction chain, with the
     frame's time window stored as the observation span. The pipeline still finishes when the
     Beta API is disabled.
  3. Speech: request Cloudinary auto-transcription, ingest the `.transcript` if it is already
     there, otherwise queue a short follow-up that does not block the asset.

Every observation from a segment carries start_ms/end_ms. Segment embeddings are written by the
shared indexer, which is what lets search return "Video 00:21-00:37".
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import structlog
from evidentia_ai.chain import run_chain
from evidentia_ai.normalize import ObservationDraft, from_extraction
from evidentia_ai.prompts import PROMPT_VERSION, AnalysisContext, extraction_prompt, prompt_hash
from evidentia_ai.providers import ImageInput
from evidentia_ai.schemas import SCHEMA_VERSION
from evidentia_cloudinary import admin
from evidentia_cloudinary.delivery import frame_url
from evidentia_cloudinary.errors import (
    CloudinaryError,
    CloudinaryNotFound,
    CloudinaryPermanentError,
    CloudinaryRetryableError,
)
from evidentia_cloudinary.video import VideoAnalysisClient
from evidentia_core import tasks as task_names
from evidentia_core.db.models import Asset, Derivative, Observation, Project, Site
from evidentia_core.domain.enums import (
    AnalysisTask,
    AssetState,
    ObservationStatus,
    OntologyType,
    ResourceType,
)
from evidentia_core.domain.taxonomy import Activity
from evidentia_core.domain.video import (
    VISUAL_PROMPT,
    keyframe_seconds,
    speech_segments,
    visual_segments,
    windows_for,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from evidentia_worker.context import WorkerContext
from evidentia_worker.errors import PermanentError, RetryableError
from evidentia_worker.pipeline import runs
from evidentia_worker.pipeline.enrichment import (
    _cloudinary_native,
    _load_taxonomy,
    model_input,
)
from evidentia_worker.pipeline.indexing import index_asset
from evidentia_worker.pipeline.runs import PermanentRunFailure, RunOutput, RunSpec
from evidentia_worker.pipeline.state import transition

log = structlog.get_logger("evidentia.video")


def enrich_video(session: Session, asset: Asset, ctx: WorkerContext) -> None:
    if asset.resource_type != ResourceType.VIDEO:
        raise PermanentError("video enrichment called for a non-video asset")
    if asset.state == AssetState.DEDUP_CHECKED:
        transition(session, asset, AssetState.ANALYZING, ctx, reason="video enrichment running")

    project = session.get(Project, asset.project_id)
    assert project is not None
    site = session.get(Site, asset.site_id) if asset.site_id else None
    activities, taxonomy_version = _load_taxonomy(session, project)
    _request_transcription(session, asset, ctx)

    used_visual = _visual_analysis(session, asset, ctx)
    image = model_input(session, asset, ctx)
    _cloudinary_native(session, asset, ctx, image, activities, taxonomy_version)
    if not used_visual:
        frames = _keyframes(session, asset, ctx, project, site, activities, taxonomy_version)
        if frames == 0:
            _representative_frame(
                session, asset, ctx, project, site, activities, taxonomy_version, image
            )
            _set_flag(session, asset, "video_pipeline", "representative_frame")
        else:
            _set_flag(session, asset, "video_pipeline", "keyframes")
    else:
        _set_flag(session, asset, "video_pipeline", "visual")

    _ingest_speech(session, asset, ctx, queue_followup=True)

    flags = dict(asset.flags or {})
    flags["analyzed_at"] = datetime.now(UTC).isoformat()
    asset.flags = flags
    index_asset(session, asset, ctx, image=image.data)
    transition(
        session, asset, AssetState.INDEXED, ctx, reason="video observations stored + indexed"
    )


def pull_speech(session: Session, asset: Asset, ctx: WorkerContext) -> str:
    """Ingest a transcript that was not ready during the main pipeline. Safe to call twice."""
    if asset.resource_type != ResourceType.VIDEO:
        return "not_video"
    stored = _ingest_speech(session, asset, ctx, queue_followup=False)
    if stored:
        index_asset(session, asset, ctx)
        session.commit()
    return "stored" if stored else "missing"


def _visual_analysis(session: Session, asset: Asset, ctx: WorkerContext) -> bool:
    settings = ctx.settings
    if (
        not settings.cloudinary_video_analysis_enabled
        or ctx.creds is None
        or not asset.cloudinary_asset_id
    ):
        return False
    client = VideoAnalysisClient(
        ctx.creds, http=ctx.http, timeout=settings.ai_request_timeout_seconds
    )
    spec = RunSpec(
        AnalysisTask.VIDEO_VISUAL,
        "cloudinary",
        "ai_video_analysis",
        prompt_version="video-visual-1",
        input={"prompt": VISUAL_PROMPT},
    )

    def work() -> RunOutput:
        flags = dict(asset.flags or {})
        job_id = flags.get("video_analysis_job_id")
        try:
            if not job_id:
                job_id = client.start(asset.cloudinary_asset_id or "", VISUAL_PROMPT)
                flags["video_analysis_job_id"] = job_id
                asset.flags = flags
                session.commit()
            job = client.status(str(job_id))
        except CloudinaryPermanentError as exc:
            raise PermanentRunFailure(str(exc)) from exc
        except CloudinaryRetryableError as exc:
            raise RetryableError(str(exc)) from exc
        if job.status == "failed":
            raise PermanentRunFailure(job.error or "video analysis failed")
        if job.status != "completed" or not job.url:
            raise RetryableError(f"video analysis {job.status}")
        try:
            rows = client.fetch(job.url)
        except CloudinaryPermanentError as exc:
            raise PermanentRunFailure(str(exc)) from exc
        except CloudinaryRetryableError as exc:
            raise RetryableError(str(exc)) from exc
        segments = visual_segments(rows)
        if not segments:
            raise PermanentRunFailure("video analysis returned no segments")
        return RunOutput(
            drafts=[_visual_draft(item) for item in segments],
            raw={"job_id": job_id, "segments": len(segments)},
            provider="cloudinary",
            model="ai_video_analysis",
        )

    run, _output = runs.execute(session, asset, spec, work)
    return run.status.value == "succeeded"


def _keyframes(
    session: Session,
    asset: Asset,
    ctx: WorkerContext,
    project: Project,
    site: Site | None,
    activities: list[Activity],
    taxonomy_version: int,
) -> int:
    stored = 0
    offsets = keyframe_seconds(asset.duration_seconds)
    for seconds, start_s, end_s in windows_for(offsets, asset.duration_seconds):
        frame = _download_frame(session, asset, ctx, seconds)
        if frame is None:
            continue
        data, _transformation = frame
        span = {
            "type": "segment",
            "start_ms": round(start_s * 1000),
            "end_ms": max(round(end_s * 1000), round(start_s * 1000) + 200),
        }
        analysis_ctx = AnalysisContext(
            project_name=project.name,
            activities=activities,
            site_name=site.name if site else None,
            declared_activity=asset.declared_activity,
            media_kind=f"video frame at {seconds:.1f}s",
        )
        if _extract_frame(
            session,
            asset,
            ctx,
            data,
            analysis_ctx,
            taxonomy_version,
            span,
            extra_key=f"kf{seconds}",
        ):
            stored += 1
    return stored


def _representative_frame(
    session: Session,
    asset: Asset,
    ctx: WorkerContext,
    project: Project,
    site: Site | None,
    activities: list[Activity],
    taxonomy_version: int,
    image: ImageInput,
) -> None:
    """Last resort: the named midpoint frame (`so_50p`), which strict transformations allow."""
    analysis_ctx = AnalysisContext(
        project_name=project.name,
        activities=activities,
        site_name=site.name if site else None,
        declared_activity=asset.declared_activity,
        media_kind="video frame",
    )
    _extract_frame(
        session,
        asset,
        ctx,
        image.data,
        analysis_ctx,
        taxonomy_version,
        {"type": "frame", "offset": "50p"},
        extra_key="representative",
        cloudinary_url=image.cloudinary_url,
    )


def _extract_frame(
    session: Session,
    asset: Asset,
    ctx: WorkerContext,
    data: bytes,
    analysis_ctx: AnalysisContext,
    taxonomy_version: int,
    span: dict[str, object],
    *,
    extra_key: str,
    cloudinary_url: str | None = None,
) -> bool:
    prompt = extraction_prompt(analysis_ctx)
    spec = RunSpec(
        AnalysisTask.VISION_EXTRACT,
        provider="chain",
        model="chain",
        prompt_version=PROMPT_VERSION,
        prompt_hash=prompt_hash(prompt),
        schema_version=SCHEMA_VERSION,
        taxonomy_version=taxonomy_version,
        extra_key=extra_key,
        input={"providers": [p.name for p in ctx.providers], "span": span},
    )
    if not ctx.providers:
        return False
    image = ImageInput(data=data, mime_type="image/jpeg", cloudinary_url=cloudinary_url)

    def extract() -> RunOutput:
        outcome = run_chain(ctx.providers, image, analysis_ctx, prompt)
        if outcome.result is None:
            if outcome.only_transient_failures:
                raise RetryableError("all vision providers failed transiently")
            raise PermanentRunFailure("no vision provider produced a valid extraction")
        result = outcome.result
        return RunOutput(
            drafts=from_extraction(result.extraction, span=span),  # type: ignore[arg-type]
            raw={"provider": result.provider, "extraction": result.extraction.model_dump()},
            latency_ms=result.latency_ms,
            model=result.model,
            provider=result.provider,
            model_version=result.model_version,
            payload=result.extraction,
        )

    run, _output = runs.execute(session, asset, spec, extract)
    return run.status.value == "succeeded"


def _download_frame(
    session: Session, asset: Asset, ctx: WorkerContext, seconds: float
) -> tuple[bytes, str] | None:
    rendition = frame_url(asset.public_id, seconds)
    url = rendition.url
    response = _get(ctx, url)
    if response is None or response.status_code in {400, 401, 403}:
        generated = _explicit_frame(asset, rendition.transformation)
        if generated is None:
            log.info("keyframe_skipped", asset_id=str(asset.id), seconds=seconds)
            return None
        url = generated
        response = _get(ctx, url)
    if response is None or response.status_code >= 400 or not response.content:
        log.info(
            "keyframe_skipped",
            asset_id=str(asset.id),
            seconds=seconds,
            status=None if response is None else response.status_code,
        )
        return None
    _record_derivative(session, asset, "keyframe", rendition.transformation, len(response.content))
    return response.content, rendition.transformation


def _explicit_frame(asset: Asset, transformation: str) -> str | None:
    try:
        return admin.video_frame(asset.public_id, transformation)
    except CloudinaryError as exc:
        log.info("keyframe_explicit_failed", asset_id=str(asset.id), error=str(exc)[:200])
        return None


def _get(ctx: WorkerContext, url: str) -> httpx.Response | None:
    try:
        return ctx.http.get(url)
    except httpx.TransportError as exc:
        log.info("keyframe_download_failed", error=str(exc)[:200])
        return None


def _request_transcription(session: Session, asset: Asset, ctx: WorkerContext) -> None:
    if not ctx.settings.cloudinary_video_transcription_enabled or ctx.creds is None:
        return
    flags = dict(asset.flags or {})
    if flags.get("speech_requested") or flags.get("speech_unavailable"):
        return
    try:
        admin.request_auto_transcription(asset.public_id)
    except CloudinaryPermanentError as exc:
        flags["speech_unavailable"] = str(exc)[:200]
        asset.flags = flags
        session.commit()
        return
    except CloudinaryRetryableError as exc:
        log.warning("speech_request_retryable", asset_id=str(asset.id), error=str(exc)[:200])
        return
    flags["speech_requested"] = True
    asset.flags = flags
    session.commit()


def _ingest_speech(
    session: Session, asset: Asset, ctx: WorkerContext, *, queue_followup: bool
) -> bool:
    if not ctx.settings.cloudinary_video_transcription_enabled or ctx.creds is None:
        return False
    if (asset.flags or {}).get("speech_unavailable"):
        return False
    spec = RunSpec(
        AnalysisTask.SPEECH, "cloudinary", "auto_transcription", prompt_version="speech-1"
    )

    def work() -> RunOutput:
        try:
            rows = admin.fetch_transcript_json(f"{asset.public_id}.transcript")
        except CloudinaryNotFound as exc:
            raise PermanentRunFailure("transcript not ready") from exc
        except CloudinaryPermanentError as exc:
            raise PermanentRunFailure(str(exc)) from exc
        except CloudinaryRetryableError as exc:
            raise RetryableError(str(exc)) from exc
        segments = speech_segments(rows)
        if not segments:
            raise PermanentRunFailure("transcript was empty")
        return RunOutput(
            drafts=[_speech_draft(item) for item in segments],
            raw={"segments": len(segments)},
            provider="cloudinary",
            model="auto_transcription",
        )

    run, output = runs.execute(session, asset, spec, work)
    if run.status.value == "succeeded":
        return output is not None or _has_speech(session, asset)
    if queue_followup and (run.error or "").startswith("transcript not ready"):
        _queue_speech_followup(asset)
    return False


def _has_speech(session: Session, asset: Asset) -> bool:
    found = session.scalar(
        select(Observation.id).where(
            Observation.asset_id == asset.id,
            Observation.ontology_type == OntologyType.DOCUMENT_TEXT,
            Observation.subject == "speech",
            Observation.status != ObservationStatus.SUPERSEDED,
            Observation.generation == asset.analysis_generation,
        )
    )
    return found is not None


def _queue_speech_followup(asset: Asset) -> None:
    try:
        from evidentia_worker.celery_app import app

        app.send_task(task_names.INGEST_SPEECH, args=[str(asset.id)], countdown=30)
    except Exception as exc:  # a missing broker must not fail evidence
        log.warning("speech_followup_not_queued", asset_id=str(asset.id), error=str(exc)[:200])


def _visual_draft(item: dict[str, object]) -> ObservationDraft:
    return ObservationDraft(
        OntologyType.SCENE,
        "video",
        "described",
        value={"text": item["text"], "via": "cloudinary_video_analysis"},
        evidence_span=item["span"],  # type: ignore[arg-type]
    )


def _speech_draft(item: dict[str, object]) -> ObservationDraft:
    return ObservationDraft(
        OntologyType.DOCUMENT_TEXT,
        "speech",
        "transcribed",
        confidence=item.get("confidence") if isinstance(item.get("confidence"), float) else None,
        value={"text": item["text"], "untrusted": True, "via": "speech"},
        evidence_span=item["span"],  # type: ignore[arg-type]
    )


def _record_derivative(
    session: Session, asset: Asset, purpose: str, transformation: str, nbytes: int
) -> None:
    already = session.scalar(
        select(Derivative.id).where(
            Derivative.asset_id == asset.id,
            Derivative.purpose == purpose,
            Derivative.transformation == transformation,
        )
    )
    if already is not None:
        return
    session.add(
        Derivative(
            organization_id=asset.organization_id,
            asset_id=asset.id,
            purpose=purpose,
            transformation=transformation,
            format="jpg" if purpose == "keyframe" else "mp4",
            source="on_demand",
            bytes=nbytes,
        )
    )
    session.commit()


def _set_flag(session: Session, asset: Asset, key: str, value: str) -> None:
    flags = dict(asset.flags or {})
    flags[key] = value
    asset.flags = flags
    session.commit()
