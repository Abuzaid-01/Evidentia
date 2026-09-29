"""REGISTERED -> METADATA_READY: capture time, location, integrity hash, consistency checks.

Every derived value records *where it came from* (EXIF, user, upload time...). Reports later show
"GPS from EXIF, unverified" instead of presenting metadata as fact.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import httpx
from evidentia_cloudinary.delivery import original_download_url
from evidentia_cloudinary.exif import extract_capture_info
from evidentia_core.db.models import Asset, Project, Site
from evidentia_core.domain.enums import AssetState, ProvenanceSource
from evidentia_core.domain.geo import haversine_m, valid_coordinates
from sqlalchemy.orm import Session

from evidentia_worker.context import WorkerContext
from evidentia_worker.errors import RetryableError
from evidentia_worker.pipeline.state import transition

PROJECT_WINDOW_SLACK = timedelta(days=30)


def _sha256_of_original(asset: Asset, ctx: WorkerContext) -> str | None:
    if not asset.format or (asset.bytes or 0) > ctx.settings.sha256_max_bytes:
        return None
    url = original_download_url(
        asset.public_id, asset.resource_type.value, asset.format, ttl_seconds=900
    )
    digest = hashlib.sha256()
    try:
        with ctx.http.stream("GET", url.url) as response:
            if response.status_code >= 500 or response.status_code == 429:
                raise RetryableError(f"original download: HTTP {response.status_code}")
            if response.status_code >= 400:
                return None  # e.g. plan restrictions: integrity hash is best-effort, never blocking
            for chunk in response.iter_bytes(1024 * 1024):
                digest.update(chunk)
    except httpx.TransportError as exc:
        raise RetryableError(f"original download failed: {exc}") from exc
    return digest.hexdigest()


def extract_provenance(session: Session, asset: Asset, ctx: WorkerContext) -> None:
    info = extract_capture_info(asset.media_metadata or {})
    flags = dict(asset.flags or {})

    if info.capture_time:
        asset.capture_time, asset.capture_time_source = info.capture_time, ProvenanceSource.EXIF
    elif asset.declared_capture_time:
        asset.capture_time, asset.capture_time_source = (
            asset.declared_capture_time,
            ProvenanceSource.USER,
        )
    elif asset.uploaded_at:
        asset.capture_time, asset.capture_time_source = asset.uploaded_at, ProvenanceSource.UPLOAD

    if valid_coordinates(info.latitude, info.longitude):
        asset.latitude, asset.longitude = info.latitude, info.longitude
        asset.location_source = ProvenanceSource.EXIF
    asset.exif = info.curated or None

    # --- consistency checks (review signals, never automatic rejections) -----------------------
    site = session.get(Site, asset.site_id) if asset.site_id else None
    if site and site.latitude is not None and asset.latitude is not None:
        distance = haversine_m(asset.latitude, asset.longitude, site.latitude, site.longitude)  # type: ignore[arg-type]
        if distance > site.radius_m:
            flags["geo_outside_site_m"] = round(distance)
        else:
            flags.pop("geo_outside_site_m", None)

    project = session.get(Project, asset.project_id)
    if project and asset.capture_time and asset.capture_time_source != ProvenanceSource.UPLOAD:
        captured = asset.capture_time.date()
        too_early = project.starts_on and captured < project.starts_on - PROJECT_WINDOW_SLACK
        too_late = project.ends_on and captured > project.ends_on + PROJECT_WINDOW_SLACK
        flags["capture_outside_project_window"] = bool(too_early or too_late)
    if asset.capture_time and asset.capture_time > datetime.now(UTC) + timedelta(days=1):
        flags["capture_time_in_future"] = True

    asset.sha256 = _sha256_of_original(asset, ctx)
    asset.flags = flags
    transition(session, asset, AssetState.METADATA_READY, ctx)
