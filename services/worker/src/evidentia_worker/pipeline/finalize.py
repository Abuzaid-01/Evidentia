"""INDEXED -> REVIEW_REQUIRED | READY.

Summarises the observations, scores review priority, explains *why* an asset needs a human, and
writes the AI summary back to Cloudinary so the Media Library stays a useful DAM.
"""

from __future__ import annotations

from typing import Any

import structlog
from evidentia_cloudinary import admin
from evidentia_cloudinary.errors import CloudinaryError
from evidentia_core.db.models import Asset, AuditEvent, Observation
from evidentia_core.domain import review
from evidentia_core.domain.enums import (
    ActorKind,
    AssetState,
    ObservationStatus,
    OntologyType,
    SourceKind,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from evidentia_worker.context import WorkerContext
from evidentia_worker.pipeline.indexing import index_asset
from evidentia_worker.pipeline.state import transition

log = structlog.get_logger("evidentia.finalize")


def _quality_score(analysis: dict[str, Any] | None) -> float | None:
    """Tolerant read of Cloudinary's image_quality result (Beta shape): first numeric *score*."""

    def walk(node: Any) -> float | None:
        if isinstance(node, dict):
            for key, value in node.items():
                if "score" in key.lower() and isinstance(value, int | float):
                    return float(value)
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found is not None:
                    return found
        return None

    return walk(analysis) if analysis else None


def finalize(session: Session, asset: Asset, ctx: WorkerContext) -> None:
    observations = list(
        session.scalars(
            select(Observation).where(
                Observation.asset_id == asset.id,
                Observation.generation == asset.analysis_generation,
                Observation.source_kind == SourceKind.AI,
                Observation.status == ObservationStatus.PROPOSED,
            )
        )
    )
    by_type: dict[OntologyType, list[Observation]] = {}
    for obs in observations:
        by_type.setdefault(obs.ontology_type, []).append(obs)

    # --- caption: Cloudinary captioning first, then a frame caption, then the first video segment
    captions = [o for o in by_type.get(OntologyType.SCENE, []) if o.predicate == "caption"]
    captions.sort(
        key=lambda o: (
            0 if (o.value or {}).get("via") == "cloudinary_captioning" else 1,
            (o.evidence_span or {}).get("start_ms", 0),
        )
    )
    if captions:
        asset.caption = (captions[0].value or {}).get("text")
    else:
        described = [o for o in by_type.get(OntologyType.SCENE, []) if o.predicate == "described"]
        described.sort(key=lambda o: (o.evidence_span or {}).get("start_ms", 0))
        asset.caption = (described[0].value or {}).get("text") if described else None

    # --- activities + corroboration ---------------------------------------------------------------
    activity_obs = by_type.get(OntologyType.ACTIVITY, [])
    depicted = [o for o in activity_obs if o.predicate == "depicted" and o.subject != "other"]
    tagged = {o.subject for o in activity_obs if o.predicate == "tagged"}
    declared = asset.declared_activity
    flags = dict(asset.flags or {})
    meta_uncertainty = review.metadata_uncertainty(
        asset.capture_time_source.value, asset.location_source.value
    )
    inconsistency = (
        1.0
        if (
            flags.get("geo_outside_site_m")
            or flags.get("capture_outside_project_window")
            or flags.get("capture_time_in_future")
        )
        else 0.0
    )

    for obs in depicted:
        corroborated = obs.subject in tagged or obs.subject == declared
        signals = review.ReviewSignals(
            model_uncertainty=review.model_uncertainty(obs.confidence),
            metadata_uncertainty=meta_uncertainty,
            geo_time_inconsistency=inconsistency,
            lack_of_corroboration=0.0 if corroborated else 1.0,
        )
        obs.review_priority = signals.score()
        obs.review_signals = {
            **signals.explain(),
            "corroborated_by": _corroboration(obs.subject, tagged, declared),
        }

    top = max(depicted, key=lambda o: o.confidence or 0.0, default=None)
    asset.top_activity = top.subject if top else None
    asset.top_activity_confidence = top.confidence if top else None

    quality = by_type.get(OntologyType.QUALITY, [])
    asset.quality_score = next(
        (
            s
            for s in (_quality_score((o.value or {}).get("analysis")) for o in quality)
            if s is not None
        ),
        None,
    )

    # --- flags & review reasons --------------------------------------------------------------------
    sensitive = sorted({o.subject for o in by_type.get(OntologyType.SENSITIVE, [])})
    flags["people_present"] = bool(by_type.get(OntologyType.PEOPLE))
    flags["sensitive"] = sensitive
    flags["text_present"] = bool(by_type.get(OntologyType.DOCUMENT_TEXT))
    flags["quality_issues"] = [
        (o.value or {}).get("issue") for o in quality if (o.value or {}).get("issue")
    ]
    asset.flags = flags

    reasons: list[str] = []
    threshold = ctx.settings.review_confidence_threshold
    if not flags.get("vision_extraction"):
        reasons.append("No AI extraction available: needs manual description")
    if top is None and flags.get("vision_extraction"):
        reasons.append("No project activity recognised")
    if top and (top.confidence or 0) < threshold:
        reasons.append(
            f"Top activity '{top.subject}' below confidence threshold ({top.confidence:.2f})"
        )
    if top and top.review_signals and not top.review_signals.get("corroborated_by"):
        reasons.append(f"Activity '{top.subject}' not corroborated by tagging or the field team")
    if declared and top and declared != top.subject:
        reasons.append(f"Field team said '{declared}', AI saw '{top.subject}'")
    if asset.exact_duplicate_of_id:
        reasons.append("Exact duplicate of an existing asset")
    if asset.near_duplicates:
        reasons.append(f"{len(asset.near_duplicates)} visually similar asset(s)")
    if flags.get("geo_outside_site_m"):
        reasons.append(f"GPS is {flags['geo_outside_site_m']} m from the site")
    if flags.get("capture_outside_project_window"):
        reasons.append("Captured outside the project period")
    if flags.get("capture_time_in_future"):
        reasons.append("Capture time is in the future")
    if sensitive:
        reasons.append(f"Sensitive content: {', '.join(sensitive)}")

    asset.review_reasons = reasons or None
    asset.review_priority = max(
        (o.review_priority or 0.0 for o in depicted), default=0.5 if reasons else 0.0
    )
    target = AssetState.REVIEW_REQUIRED if reasons else AssetState.READY

    session.add(
        AuditEvent(
            organization_id=asset.organization_id,
            actor_kind=ActorKind.SYSTEM,
            action="asset.analyzed",
            target_type="asset",
            target_id=asset.id,
            data={
                "generation": asset.analysis_generation,
                "observations": len(observations),
                "top_activity": asset.top_activity,
                "outcome": target.value,
            },
        )
    )
    index_asset(session, asset, ctx)  # refresh text document now that the caption is chosen
    transition(session, asset, target, ctx, reason="; ".join(reasons) if reasons else "ready")
    _write_back(asset, ctx)


def _corroboration(subject: str, tagged: set[str], declared: str | None) -> list[str]:
    sources = []
    if subject in tagged:
        sources.append("cloudinary_ai_vision_tagging")
    if subject == declared:
        sources.append("field_team")
    return sources


def _write_back(asset: Asset, ctx: WorkerContext) -> None:
    """Mirror the AI summary into Cloudinary (context + tags). Best-effort, never fails the asset."""
    if not ctx.settings.cloudinary_writeback_enabled or ctx.creds is None:
        return
    rt = asset.resource_type.value
    try:
        context = {"ev_state": asset.state.value}
        if asset.caption:
            context["ev_caption"] = asset.caption[:250]
        if asset.top_activity:
            context["ev_top_activity"] = asset.top_activity
        admin.add_context(asset.public_id, rt, context)
        if (
            asset.top_activity
            and (asset.top_activity_confidence or 0) >= ctx.settings.review_confidence_threshold
        ):
            admin.add_tags(asset.public_id, rt, [f"ai_{asset.top_activity}"])
        if ctx.settings.cloudinary_use_structured_metadata:
            status = "needs_review" if asset.state == AssetState.REVIEW_REQUIRED else "unreviewed"
            admin.update_structured_metadata(
                asset.public_id, rt, {"ev_verification_status": status}
            )
    except CloudinaryError as exc:
        log.warning("cloudinary_writeback_failed", asset_id=str(asset.id), error=str(exc))
