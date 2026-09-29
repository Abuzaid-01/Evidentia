"""Re-indexing tasks: after reviews (text changes), model changes, or to backfill existing assets."""

from __future__ import annotations

import uuid

import structlog
from evidentia_core import tasks
from evidentia_core.db.models import Asset
from evidentia_core.db.session import set_session_tenant, sync_system_session
from evidentia_core.domain.enums import AssetState
from sqlalchemy import select

from evidentia_worker.celery_app import app
from evidentia_worker.context import get_context
from evidentia_worker.errors import TRANSIENT_EXCEPTIONS
from evidentia_worker.pipeline.enrichment import model_input
from evidentia_worker.pipeline.indexing import index_asset

log = structlog.get_logger("evidentia.search.tasks")

INDEXABLE = (AssetState.READY, AssetState.REVIEW_REQUIRED)


@app.task(
    name=tasks.REINDEX_ASSET,
    bind=True,
    max_retries=5,
    autoretry_for=TRANSIENT_EXCEPTIONS,
    retry_backoff=True,
)
def reindex_asset(self, asset_id: str, with_image: bool = False) -> str:  # type: ignore[no-untyped-def]
    ctx = get_context()
    with sync_system_session() as session:
        asset = session.get(Asset, uuid.UUID(asset_id))
        if asset is None or asset.state not in INDEXABLE:
            return "skipped"
        set_session_tenant(session, asset.organization_id)
        image = model_input(session, asset, ctx).data if with_image and ctx.creds else None
        index_asset(session, asset, ctx, image=image)
        session.commit()
    return "indexed"


@app.task(name=tasks.REINDEX_PROJECT)
def reindex_project(project_id: str, with_image: bool = True) -> int:
    """Backfill: enqueue a re-index for every searchable asset of a project."""
    with sync_system_session() as session:
        ids = list(
            session.scalars(
                select(Asset.id).where(
                    Asset.project_id == uuid.UUID(project_id), Asset.state.in_(INDEXABLE)
                )
            )
        )
    for aid in ids:
        reindex_asset.delay(str(aid), with_image)
    log.info("reindex_project", project_id=project_id, assets=len(ids))
    return len(ids)
