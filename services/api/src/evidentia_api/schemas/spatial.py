"""Schemas for spatial-temporal map and timeline views (PLAN Phase 9)."""

from __future__ import annotations

import uuid
from datetime import datetime

from evidentia_api.schemas.common import ApiModel


class SpatialPoint(ApiModel):
    asset_id: uuid.UUID
    latitude: float
    longitude: float
    location_source: str
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    site_code: str | None = None
    capture_time: datetime | None = None
    activity: str | None = None
    verified: bool = False
    caption: str | None = None
    thumbnail_url: str | None = None
    resource_type: str = "image"


class SpatialSite(ApiModel):
    site_id: uuid.UUID
    name: str
    code: str
    latitude: float | None = None
    longitude: float | None = None
    asset_count: int = 0


class TimelineBucket(ApiModel):
    date: str  # YYYY-MM-DD
    count: int
    activities: dict[str, int]


class SpatialBounds(ApiModel):
    min_lat: float | None = None
    max_lat: float | None = None
    min_lng: float | None = None
    max_lng: float | None = None
    center_lat: float | None = None
    center_lng: float | None = None


class SpatialTemporalOut(ApiModel):
    project_id: uuid.UUID
    total_geotagged: int
    points: list[SpatialPoint]
    sites: list[SpatialSite]
    timeline: list[TimelineBucket]
    bounds: SpatialBounds
