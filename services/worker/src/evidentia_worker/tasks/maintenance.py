"""Periodic housekeeping (Celery beat)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from evidentia_core import tasks
from evidentia_core.db.models import Asset
from evidentia_core.db.session import sync_system_session
from evidentia_core.domain.enums import AssetState
from sqlalchemy import update

from evidentia_worker.celery_app import app
from evidentia_worker.context import get_context
from evidentia_worker.pipeline.orchestrator import stale_uploaded_assets

log = structlog.get_logger("evidentia.maintenance")


@app.task(name=tasks.EXPIRE_STALE_UPLOADS)
def expire_stale_uploads() -> dict[str, int]:
    """1) Expire upload intents that never received bytes.
    2) Re-enqueue assets stuck in UPLOADED (e.g. the broker was down when they were confirmed)."""
    settings = get_context().settings
    now = datetime.now(UTC)
    with sync_system_session() as session:
        expired = session.execute(
            update(Asset)
            .where(
                Asset.state == AssetState.AWAITING_UPLOAD,
                Asset.created_at < now - timedelta(hours=settings.upload_intent_ttl_hours),
            )
            .values(
                state=AssetState.EXPIRED,
                state_reason="upload never completed",
                state_changed_at=now,
            )
        ).rowcount
        stuck = stale_uploaded_assets(session, now - timedelta(minutes=5))
        session.commit()

    for asset_id in stuck:
        tasks.enqueue(tasks.PROCESS_ASSET, str(asset_id))
    result = {"expired": int(expired or 0), "requeued": len(stuck)}
    if any(result.values()):
        log.info("sweep", **result)
    return result
