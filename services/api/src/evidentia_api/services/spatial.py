"""Spatial-temporal data assembly for map and timeline views (PLAN Phase 9)."""

from __future__ import annotations

import uuid
from collections import defaultdict

from evidentia_core.config import Settings
from evidentia_core.db.models import Asset, Site
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.schemas.spatial import (
    SpatialBounds,
    SpatialPoint,
    SpatialSite,
    SpatialTemporalOut,
    TimelineBucket,
)
from evidentia_api.services.assets import thumb_url


async def get_spatial_temporal(
    session: AsyncSession,
    project_id: uuid.UUID,
    settings: Settings,
    *,
    cloudinary_ready: bool,
) -> SpatialTemporalOut:
    sites_rows = (
        await session.scalars(select(Site).where(Site.project_id == project_id).order_by(Site.name))
    ).all()
    site_map = {s.id: s for s in sites_rows}

    assets_rows = (
        await session.scalars(
            select(Asset)
            .where(Asset.project_id == project_id)
            .order_by(Asset.capture_time.asc().nulls_last(), Asset.created_at.asc())
        )
    ).all()

    site_counts = defaultdict(int)
    points: list[SpatialPoint] = []
    timeline_counts: dict[str, int] = defaultdict(int)
    timeline_activities: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for asset in assets_rows:
        if asset.site_id and asset.site_id in site_map:
            site_counts[asset.site_id] += 1

        # Timeline grouping (use capture_time if available, otherwise created_at)
        dt = asset.capture_time or asset.created_at
        date_str = dt.strftime("%Y-%m-%d") if dt else "undated"
        timeline_counts[date_str] += 1
        act = asset.top_activity or asset.declared_activity or "unclassified"
        timeline_activities[date_str][act] += 1

        # Geotagged points
        lat = asset.latitude
        lng = asset.longitude
        source = (
            asset.location_source.value
            if hasattr(asset.location_source, "value")
            else str(asset.location_source)
        )

        # If asset doesn't have coordinates, fall back to its site coordinates if present
        if (lat is None or lng is None) and asset.site_id and asset.site_id in site_map:
            site = site_map[asset.site_id]
            if site.latitude is not None and site.longitude is not None:
                lat = site.latitude
                lng = site.longitude
                source = "site_inferred"

        if lat is not None and lng is not None:
            site = site_map.get(asset.site_id) if asset.site_id else None
            is_verified = bool(asset.verified_activities and len(asset.verified_activities) > 0)
            points.append(
                SpatialPoint(
                    asset_id=asset.id,
                    latitude=lat,
                    longitude=lng,
                    location_source=source,
                    site_id=site.id if site else None,
                    site_name=site.name if site else None,
                    site_code=site.code if site else None,
                    capture_time=asset.capture_time,
                    activity=asset.top_activity or asset.declared_activity,
                    verified=is_verified,
                    caption=asset.caption,
                    thumbnail_url=thumb_url(asset, settings, cloudinary_ready=cloudinary_ready),
                    resource_type=asset.resource_type.value
                    if hasattr(asset.resource_type, "value")
                    else str(asset.resource_type),
                )
            )

    # Sites list
    sites_out: list[SpatialSite] = [
        SpatialSite(
            site_id=s.id,
            name=s.name,
            code=s.code,
            latitude=s.latitude,
            longitude=s.longitude,
            asset_count=site_counts[s.id],
        )
        for s in sites_rows
    ]

    # Timeline buckets
    timeline_buckets: list[TimelineBucket] = [
        TimelineBucket(date=d, count=timeline_counts[d], activities=dict(timeline_activities[d]))
        for d in sorted(timeline_counts.keys())
        if d != "undated"
    ]

    # Spatial Bounds
    if points:
        lats = [p.latitude for p in points]
        lngs = [p.longitude for p in points]
        bounds = SpatialBounds(
            min_lat=round(min(lats), 6),
            max_lat=round(max(lats), 6),
            min_lng=round(min(lngs), 6),
            max_lng=round(max(lngs), 6),
            center_lat=round((min(lats) + max(lats)) / 2, 6),
            center_lng=round((min(lngs) + max(lngs)) / 2, 6),
        )
    else:
        # Default to site coordinates if available
        site_lats = [s.latitude for s in sites_rows if s.latitude is not None]
        site_lngs = [s.longitude for s in sites_rows if s.longitude is not None]
        if site_lats and site_lngs:
            bounds = SpatialBounds(
                min_lat=round(min(site_lats), 6),
                max_lat=round(max(site_lats), 6),
                min_lng=round(min(site_lngs), 6),
                max_lng=round(max(site_lngs), 6),
                center_lat=round((min(site_lats) + max(site_lats)) / 2, 6),
                center_lng=round((min(site_lngs) + max(site_lngs)) / 2, 6),
            )
        else:
            bounds = SpatialBounds()

    return SpatialTemporalOut(
        project_id=project_id,
        total_geotagged=len(points),
        points=points,
        sites=sites_out,
        timeline=timeline_buckets,
        bounds=bounds,
    )
