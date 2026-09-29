"""Celery entry points for the asset pipeline."""

from __future__ import annotations

import random
import uuid

import structlog
from celery import Task
from evidentia_core import tasks
from evidentia_core.domain.state_machine import InvalidTransition

from evidentia_worker.celery_app import app
from evidentia_worker.context import get_context
from evidentia_worker.errors import TRANSIENT_EXCEPTIONS, PermanentError
from evidentia_worker.pipeline.orchestrator import (
    AssetBusy,
    mark_permanent,
    mark_retryable,
    prepare_reanalysis,
    run_pipeline,
)

log = structlog.get_logger("evidentia.tasks")
MAX_RETRIES = 6


def _backoff(retries: int) -> int:
    """Exponential backoff with full jitter: ~10s, 20s, 40s ... capped at 10 minutes."""
    return int(random.uniform(0.5, 1.0) * min(600, 10 * 2**retries))


def _run(task: Task, asset_id: str) -> str | None:
    ctx = get_context()
    aid = uuid.UUID(asset_id)
    try:
        state = run_pipeline(aid, ctx, task_id=task.request.id)
        return state.value if state else None
    except AssetBusy:
        # another worker is on it; check back shortly in case it dies
        raise task.retry(countdown=30, max_retries=MAX_RETRIES + 10) from None
    except PermanentError as exc:
        log.warning("pipeline_permanent_failure", asset_id=asset_id, error=str(exc))
        mark_permanent(aid, ctx, str(exc))
        return "failed_permanent"
    except InvalidTransition as exc:
        log.error("pipeline_invalid_transition", asset_id=asset_id, error=str(exc))
        mark_permanent(aid, ctx, f"internal state error: {exc}")
        return "failed_permanent"
    except TRANSIENT_EXCEPTIONS as exc:
        if task.request.retries >= MAX_RETRIES:
            mark_permanent(aid, ctx, f"gave up after {MAX_RETRIES} retries: {exc}")
            return "failed_permanent"
        mark_retryable(aid, ctx, str(exc))
        log.warning(
            "pipeline_retry", asset_id=asset_id, attempt=task.request.retries + 1, error=str(exc)
        )
        raise task.retry(countdown=_backoff(task.request.retries), max_retries=MAX_RETRIES) from exc


@app.task(name=tasks.PROCESS_ASSET, bind=True, max_retries=MAX_RETRIES)
def process_asset(self: Task, asset_id: str) -> str | None:
    return _run(self, asset_id)


@app.task(name=tasks.INGEST_SPEECH, bind=True, max_retries=5)
def ingest_speech(self: Task, asset_id: str) -> str:
    """Pick up a Cloudinary transcript that was not ready when the video was first analysed."""
    from evidentia_core.db.models import Asset
    from evidentia_core.db.session import set_session_tenant, sync_system_session

    from evidentia_worker.pipeline.video import pull_speech

    ctx = get_context()
    aid = uuid.UUID(asset_id)
    with sync_system_session() as session:
        asset = session.get(Asset, aid)
        if asset is None:
            return "missing"
        set_session_tenant(session, asset.organization_id)
        try:
            outcome = pull_speech(session, asset, ctx)
        except TRANSIENT_EXCEPTIONS as exc:
            raise self.retry(countdown=30, max_retries=5) from exc
    if outcome == "missing" and self.request.retries < 5:
        raise self.retry(countdown=30, max_retries=5)
    return outcome


@app.task(name=tasks.REANALYZE_ASSET, bind=True, max_retries=MAX_RETRIES)
def reanalyze_asset(self: Task, asset_id: str) -> str | None:
    # Only the first attempt bumps the generation; retries resume the same generation.
    if self.request.retries == 0 and not prepare_reanalysis(uuid.UUID(asset_id), get_context()):
        return "not_reanalyzable"
    return _run(self, asset_id)
