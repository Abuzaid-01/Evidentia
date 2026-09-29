"""UPLOADED -> REGISTERED: pull authoritative details from Cloudinary and re-validate policy."""

from __future__ import annotations

from datetime import datetime

from evidentia_cloudinary.admin import embedded_metadata, fetch_resource, phash_to_int
from evidentia_cloudinary.errors import CloudinaryNotFound
from evidentia_core.db.models import Asset
from evidentia_core.domain.enums import AssetState
from evidentia_core.domain.media_policy import MediaLimits, MediaRejected, check_stored
from sqlalchemy.orm import Session

from evidentia_worker.context import WorkerContext
from evidentia_worker.errors import PermanentError
from evidentia_worker.pipeline.state import transition


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def register(session: Session, asset: Asset, ctx: WorkerContext) -> None:
    try:
        resource = fetch_resource(asset.public_id, asset.resource_type.value)
    except CloudinaryNotFound as exc:
        raise PermanentError("Cloudinary has no stored asset for this upload") from exc

    duration = resource.get("duration")
    limits = MediaLimits(
        ctx.settings.max_image_bytes, ctx.settings.max_video_bytes, ctx.settings.max_video_seconds
    )
    try:
        check_stored(
            asset.resource_type,
            resource.get("format"),
            resource.get("bytes"),
            float(duration) if duration else None,
            limits,
        )
    except MediaRejected as exc:
        raise PermanentError(str(exc)) from exc

    asset.cloudinary_asset_id = resource.get("asset_id")
    asset.cloudinary_version = resource.get("version")
    asset.format = resource.get("format")
    asset.bytes = resource.get("bytes")
    asset.width = resource.get("width")
    asset.height = resource.get("height")
    asset.duration_seconds = float(duration) if duration else None
    asset.etag = resource.get("etag")
    asset.uploaded_at = _parse_time(resource.get("created_at"))
    asset.asset_folder = resource.get("asset_folder") or asset.asset_folder
    asset.phash = phash_to_int(resource.get("phash"))
    asset.media_metadata = embedded_metadata(resource) or None
    transition(session, asset, AssetState.REGISTERED, ctx)
