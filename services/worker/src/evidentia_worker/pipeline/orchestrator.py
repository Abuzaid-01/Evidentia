"""Drive an asset through the pipeline, resuming from whatever state it is in.

Concurrency: a Redis lock per asset ensures only one worker processes an asset at a time (the
confirm call, the webhook and the sweeper can all enqueue the same asset).
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from evidentia_core.db.models import Asset, Job, Observation
from evidentia_core.db.session import set_session_tenant, sync_system_session
from evidentia_core.domain.enums import AssetState, JobState, ObservationStatus, SourceKind
from evidentia_core.domain.state_machine import InvalidTransition
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from evidentia_worker.context import WorkerContext
from evidentia_worker.errors import PermanentError
from evidentia_worker.pipeline.dedup import check_duplicates
from evidentia_worker.pipeline.enrichment import enrich
from evidentia_worker.pipeline.finalize import finalize
from evidentia_worker.pipeline.provenance import extract_provenance
from evidentia_worker.pipeline.register import register
from evidentia_worker.pipeline.state import publish_state, transition

log = structlog.get_logger("evidentia.pipeline")

Step = Callable[[Session, Asset, WorkerContext], None]

STEPS: dict[AssetState, Step] = {
    AssetState.UPLOADED: register,
    AssetState.REGISTERED: extract_provenance,
    AssetState.METADATA_READY: check_duplicates,
    AssetState.DEDUP_CHECKED: enrich,
    AssetState.ANALYZING: enrich,  # resumes a partially analysed asset (runs are idempotent)
    AssetState.INDEXED: finalize,
}

LOCK_TIMEOUT_SECONDS = 900


class AssetBusy(Exception):
    """Another worker holds this asset's lock."""


def _job_key(asset: Asset) -> str:
    return f"pipeline:{asset.id}:{asset.analysis_generation}"


def _upsert_job(session: Session, asset: Asset, **values: object) -> None:
    session.execute(
        insert(Job)
        .values(
            organization_id=asset.organization_id,
            type="evidentia.pipeline.process_asset",
            target_type="asset",
            target_id=asset.id,
            run_key=_job_key(asset),
            **values,
        )
        .on_conflict_do_update(index_elements=[Job.run_key], set_=values)
    )


def run_pipeline(
    asset_id: uuid.UUID, ctx: WorkerContext, *, task_id: str | None = None
) -> AssetState | None:
    lock = ctx.redis.lock(f"evidentia:lock:asset:{asset_id}", timeout=LOCK_TIMEOUT_SECONDS)
    if not lock.acquire(blocking=False):
        raise AssetBusy(str(asset_id))
    try:
        with sync_system_session() as session:
            asset = session.get(Asset, asset_id)
            if asset is None:
                log.warning("asset_missing", asset_id=str(asset_id))
                return None
            # From the next transaction on, RLS restricts this session to the asset's tenant.
            set_session_tenant(session, asset.organization_id)
            structlog.contextvars.bind_contextvars(asset_id=str(asset_id))

            now = datetime.now(UTC)
            _upsert_job(
                session, asset, state=JobState.RUNNING, started_at=now, celery_task_id=task_id
            )
            session.execute(
                update(Job).where(Job.run_key == _job_key(asset)).values(attempts=Job.attempts + 1)
            )
            session.commit()

            if asset.state == AssetState.FAILED_RETRYABLE:
                resume = AssetState(
                    (asset.flags or {}).get("resume_state", AssetState.UPLOADED.value)
                )
                transition(session, asset, resume, ctx, reason="retrying")

            while (step := STEPS.get(asset.state)) is not None:
                log.info("pipeline_step", state=asset.state.value, step=step.__name__)
                step(session, asset, ctx)

            _upsert_job(
                session,
                asset,
                state=JobState.SUCCEEDED,
                finished_at=datetime.now(UTC),
                last_error=None,
            )
            session.commit()
            log.info("pipeline_done", state=asset.state.value)
            return asset.state
    finally:
        with contextlib.suppress(Exception):  # lock may have expired; nothing to release
            lock.release()


def mark_retryable(asset_id: uuid.UUID, ctx: WorkerContext, error: str) -> None:
    with sync_system_session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.state in {AssetState.READY, AssetState.REVIEW_REQUIRED}:
            return
        flags = dict(asset.flags or {})
        if asset.state != AssetState.FAILED_RETRYABLE:
            flags["resume_state"] = asset.state.value
        asset.flags = flags
        try:
            transition(
                session, asset, AssetState.FAILED_RETRYABLE, ctx, reason=error[:500], commit=False
            )
        except InvalidTransition:
            return
        _upsert_job(session, asset, state=JobState.FAILED_RETRYABLE, last_error=error[:2000])
        session.commit()
        publish_state(asset, ctx)


def mark_permanent(asset_id: uuid.UUID, ctx: WorkerContext, error: str) -> None:
    with sync_system_session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            return
        try:
            transition(
                session, asset, AssetState.FAILED_PERMANENT, ctx, reason=error[:500], commit=False
            )
        except InvalidTransition:
            return
        _upsert_job(
            session,
            asset,
            state=JobState.DEAD,
            last_error=error[:2000],
            finished_at=datetime.now(UTC),
        )
        session.commit()
        publish_state(asset, ctx)


def prepare_reanalysis(asset_id: uuid.UUID, ctx: WorkerContext) -> bool:
    """Start a new analysis generation. Proposed AI observations of the old generation become
    SUPERSEDED (kept for history); human-verified observations are untouched."""
    with sync_system_session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.state not in {
            AssetState.READY,
            AssetState.REVIEW_REQUIRED,
            AssetState.FAILED_PERMANENT,
        }:
            return False
        session.execute(
            update(Observation)
            .where(
                Observation.asset_id == asset.id,
                Observation.source_kind == SourceKind.AI,
                Observation.status == ObservationStatus.PROPOSED,
            )
            .values(status=ObservationStatus.SUPERSEDED)
        )
        asset.analysis_generation += 1
        flags = dict(asset.flags or {})
        flags.pop("resume_state", None)
        asset.flags = flags
        transition(session, asset, AssetState.DEDUP_CHECKED, ctx, reason="re-analysis requested")
        return True


def stale_uploaded_assets(session: Session, older_than: datetime) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(Asset.id).where(
                Asset.state == AssetState.UPLOADED, Asset.state_changed_at < older_than
            )
        )
    )


__all__ = [
    "AssetBusy",
    "PermanentError",
    "mark_permanent",
    "mark_retryable",
    "prepare_reanalysis",
    "run_pipeline",
    "stale_uploaded_assets",
]
