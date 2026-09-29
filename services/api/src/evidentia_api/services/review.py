"""Human verification of AI observations.

* approve -> VERIFIED;  reject -> REJECTED
* edit    -> the AI observation becomes SUPERSEDED and a new HUMAN observation (VERIFIED) replaces it
* every decision: an ObservationReview row + an audit event, in the same transaction
* completing a review moves the asset REVIEW_REQUIRED -> READY
Nothing is deleted or overwritten, so history (and old reports) stay reproducible.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

import structlog
from evidentia_core import tasks
from evidentia_core.config import Settings
from evidentia_core.db.models import Asset, Observation, ObservationReview, Project, Taxonomy
from evidentia_core.domain.enums import (
    AssetState,
    ObservationStatus,
    OntologyType,
    ReviewDecision,
    SourceKind,
)
from evidentia_core.events import EventPublisher, build_event
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.errors import Conflict, NotFound, Unprocessable
from evidentia_api.schemas.review import (
    HumanObservationIn,
    QueueItem,
    ReviewRequest,
    ReviewResult,
)
from evidentia_api.services import audit
from evidentia_api.services.assets import to_summary
from evidentia_api.services.indexing import refresh_search_document

log = structlog.get_logger("evidentia.review")

REVIEWABLE_STATES = {AssetState.REVIEW_REQUIRED, AssetState.READY}
_DECIDABLE = {ObservationStatus.PROPOSED, ObservationStatus.VERIFIED}


async def _lock_asset(db: AsyncSession, asset_id: uuid.UUID) -> Asset:
    asset = await db.scalar(select(Asset).where(Asset.id == asset_id).with_for_update())
    if asset is None:
        raise NotFound("Asset not found")
    if asset.state not in REVIEWABLE_STATES:
        raise Conflict(f"Asset is '{asset.state.value}'; only processed assets can be reviewed")
    return asset


async def _taxonomy_keys(db: AsyncSession, project_id: uuid.UUID) -> set[str]:
    project = await db.get(Project, project_id)
    taxonomy = await db.scalar(
        select(Taxonomy).where(
            Taxonomy.project_id == project_id,
            Taxonomy.version == (project.active_taxonomy_version if project else 1),
        )
    )
    return {a["key"] for a in (taxonomy.activities if taxonomy else [])} | {"other"}


def _after_commit(asset: Asset, settings: Settings) -> None:
    """Best-effort follow-ups: text embedding refresh, Cloudinary write-back, live event."""
    for task in (tasks.REINDEX_ASSET, tasks.SYNC_REVIEW_TO_CLOUDINARY):
        with contextlib.suppress(Exception):
            tasks.enqueue(task, str(asset.id))
    EventPublisher(settings.redis_url).publish(
        asset.organization_id,
        build_event(
            "asset.state_changed",
            asset_id=asset.id,
            project_id=asset.project_id,
            state=asset.state.value,
            reason=asset.state_reason,
        ),
    )


async def review_queue(
    db: AsyncSession,
    project_id: uuid.UUID,
    settings: Settings,
    *,
    cloudinary_ready: bool,
    limit: int,
) -> list[QueueItem]:
    pending = (
        select(Observation.asset_id, func.count().label("n"))
        .where(Observation.status == ObservationStatus.PROPOSED)
        .group_by(Observation.asset_id)
        .subquery()
    )
    rows = await db.execute(
        select(Asset, func.coalesce(pending.c.n, 0))
        .outerjoin(pending, pending.c.asset_id == Asset.id)
        .where(Asset.project_id == project_id, Asset.state == AssetState.REVIEW_REQUIRED)
        .order_by(Asset.review_priority.desc().nulls_last(), Asset.created_at)
        .limit(limit)
    )
    return [
        QueueItem(
            asset=to_summary(asset, settings, cloudinary_ready=cloudinary_ready),
            pending_observations=int(count),
            review_reasons=list(asset.review_reasons or []),
        )
        for asset, count in rows
    ]


async def apply_review(
    db: AsyncSession,
    principal: Principal,
    asset_id: uuid.UUID,
    body: ReviewRequest,
    settings: Settings,
    request_id: str | None,
) -> ReviewResult:
    if not body.decisions and not body.complete:
        raise Unprocessable("Nothing to do: send decisions and/or complete=true")
    asset = await _lock_asset(db, asset_id)
    now = datetime.now(UTC)
    ids = [d.observation_id for d in body.decisions]
    if len(ids) != len(set(ids)):
        raise Unprocessable("Each observation may appear only once per request")
    observations = {
        o.id: o
        for o in (
            await db.scalars(
                select(Observation).where(Observation.id.in_(ids), Observation.asset_id == asset.id)
            )
        ).all()
    }
    keys = await _taxonomy_keys(db, asset.project_id)
    replacements: dict[str, uuid.UUID] = {}

    for decision in body.decisions:
        obs = observations.get(decision.observation_id)
        if obs is None:
            raise NotFound(f"Observation {decision.observation_id} not found on this asset")
        if obs.status not in _DECIDABLE:
            raise Conflict(f"Observation {obs.id} is '{obs.status.value}' and cannot be decided")
        previous = obs.status
        replacement: Observation | None = None

        if decision.decision == ReviewDecision.APPROVE:
            obs.status = ObservationStatus.VERIFIED
        elif decision.decision == ReviewDecision.REJECT:
            obs.status = ObservationStatus.REJECTED
        else:
            edit = decision.edit
            assert edit is not None
            subject = edit.subject or obs.subject
            if obs.ontology_type == OntologyType.ACTIVITY and subject not in keys:
                raise Unprocessable(f"'{subject}' is not an activity in this project's taxonomy")
            replacement = Observation(
                organization_id=asset.organization_id,
                asset_id=asset.id,
                analysis_run_id=None,
                generation=obs.generation,
                ontology_type=obs.ontology_type,
                subject=subject,
                predicate=edit.predicate or obs.predicate,
                value=edit.value if edit.value is not None else obs.value,
                confidence=None,  # human statement, not a model score
                evidence_span=obs.evidence_span,
                source_kind=SourceKind.HUMAN,
                source_provider="reviewer",
                status=ObservationStatus.VERIFIED,
                reviewer_id=principal.user_id,
                reviewed_at=now,
                supersedes_id=obs.id,
            )
            db.add(replacement)
            await db.flush()
            obs.status = ObservationStatus.SUPERSEDED
            replacements[str(obs.id)] = replacement.id

        obs.reviewer_id, obs.reviewed_at = principal.user_id, now
        db.add(
            ObservationReview(
                organization_id=asset.organization_id,
                observation_id=obs.id,
                asset_id=asset.id,
                reviewer_id=principal.user_id,
                decision=decision.decision,
                previous_status=previous.value,
                replacement_id=replacement.id if replacement else None,
                note=decision.note,
            )
        )
        audit.record(
            db,
            org_id=asset.organization_id,
            principal=principal,
            action=f"observation.{decision.decision.value}",
            target_type="observation",
            target_id=obs.id,
            data={
                "asset_id": str(asset.id),
                "subject": obs.subject,
                "previous_status": previous.value,
                "replacement_id": str(replacement.id) if replacement else None,
                "note": decision.note,
            },
            request_id=request_id,
        )

    if body.complete:
        if asset.state == AssetState.REVIEW_REQUIRED:
            flags = dict(asset.flags or {})
            flags["resolved_review_reasons"] = asset.review_reasons or []
            asset.flags = flags
            asset.state = AssetState.READY
            asset.state_reason = "reviewed"
            asset.state_changed_at = now
        asset.reviewed_at, asset.reviewed_by_id = now, principal.user_id
        audit.record(
            db,
            org_id=asset.organization_id,
            principal=principal,
            action="asset.review_completed",
            target_type="asset",
            target_id=asset.id,
            data={"note": body.note, "decisions": len(body.decisions)},
            request_id=request_id,
        )

    await db.flush()
    await refresh_search_document(db, asset)
    await db.commit()
    _after_commit(asset, settings)
    return ReviewResult(
        asset_id=asset.id,
        state=asset.state.value,
        applied=len(body.decisions),
        verified_activities=list(asset.verified_activities or []),
        replacements=replacements,
    )


async def add_human_observation(
    db: AsyncSession,
    principal: Principal,
    asset_id: uuid.UUID,
    body: HumanObservationIn,
    settings: Settings,
    request_id: str | None,
) -> Observation:
    """A reviewer records something the AI missed. Human observations are VERIFIED by definition."""
    asset = await _lock_asset(db, asset_id)
    if body.ontology_type == OntologyType.ACTIVITY and body.subject not in await _taxonomy_keys(
        db, asset.project_id
    ):
        raise Unprocessable(f"'{body.subject}' is not an activity in this project's taxonomy")
    now = datetime.now(UTC)
    obs = Observation(
        organization_id=asset.organization_id,
        asset_id=asset.id,
        generation=asset.analysis_generation,
        ontology_type=body.ontology_type,
        subject=body.subject,
        predicate=body.predicate,
        value={**(body.value or {}), **({"note": body.note} if body.note else {})} or None,
        evidence_span=body.evidence_span,
        source_kind=SourceKind.HUMAN,
        source_provider="reviewer",
        status=ObservationStatus.VERIFIED,
        reviewer_id=principal.user_id,
        reviewed_at=now,
    )
    db.add(obs)
    await db.flush()
    audit.record(
        db,
        org_id=asset.organization_id,
        principal=principal,
        action="observation.added",
        target_type="observation",
        target_id=obs.id,
        data={"asset_id": str(asset.id), "type": body.ontology_type.value, "subject": body.subject},
        request_id=request_id,
    )
    await refresh_search_document(db, asset)
    await db.commit()
    await db.refresh(obs)
    _after_commit(asset, settings)
    return obs
