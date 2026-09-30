"""Mirror human review results into Cloudinary so the Media Library (DAM) reflects verified truth."""

from __future__ import annotations

import json
import uuid

import structlog
from evidentia_cloudinary import admin
from evidentia_cloudinary.errors import CloudinaryPermanentError, CloudinaryRetryableError
from evidentia_core import tasks
from evidentia_core.db.models import Asset
from evidentia_core.db.session import sync_system_session
from evidentia_core.domain.enums import AssetState

from evidentia_worker.celery_app import app
from evidentia_worker.context import get_context

log = structlog.get_logger("evidentia.cloudinary")


@app.task(
    name=tasks.SYNC_REVIEW_TO_CLOUDINARY,
    autoretry_for=(CloudinaryRetryableError,),
    retry_backoff=True,
    max_retries=5,
)
def sync_review(asset_id: str) -> str:
    ctx = get_context()
    if ctx.creds is None or not ctx.settings.cloudinary_writeback_enabled:
        return "disabled"
    with sync_system_session() as session:
        asset = session.get(Asset, uuid.UUID(asset_id))
        if asset is None:
            return "missing"
        public_id, rt = asset.public_id, asset.resource_type.value
        verified = list(asset.verified_activities or [])
        status = (
            "verified" if asset.state == AssetState.READY and asset.reviewed_at else "needs_review"
        )
        if asset.state == AssetState.READY and not asset.reviewed_at:
            status = "unreviewed"
    try:
        admin.add_context(
            public_id, rt, {"ev_state": status, "ev_verified_activities": ",".join(verified)}
        )
        if verified:
            admin.add_tags(public_id, rt, [f"verified_{a}" for a in verified])
        if ctx.settings.cloudinary_use_structured_metadata:
            admin.update_structured_metadata(public_id, rt, {"ev_verification_status": status})
    except CloudinaryPermanentError as exc:
        return f"failed: {exc}"
    return status


@app.task(
    name=tasks.DELETE_CLOUDINARY_MEDIA,
    autoretry_for=(CloudinaryRetryableError,),
    retry_backoff=True,
    max_retries=6,
)
def delete_media(payload: str) -> dict[str, int]:
    """Delete a deleted project's files from Cloudinary.
    `payload` is JSON: {"image": [public_id...], "video": [...], "raw": [...]}.
    Idempotent: ids that are already gone come back as "not_found" and are skipped."""
    ctx = get_context()
    if ctx.creds is None:
        return {"skipped": 1}
    counts: dict[str, int] = {}
    for resource_type, public_ids in json.loads(payload).items():
        for start in range(0, len(public_ids), 100):
            batch = public_ids[start : start + 100]
            try:
                result = admin.delete_authenticated(batch, resource_type)
            except CloudinaryPermanentError as exc:
                log.warning("cloudinary_delete_failed", resource_type=resource_type, error=str(exc))
                continue
            for outcome in result.values():
                counts[outcome] = counts.get(outcome, 0) + 1
    log.info("cloudinary_media_deleted", **counts)
    return counts
