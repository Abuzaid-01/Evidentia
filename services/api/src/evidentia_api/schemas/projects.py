from __future__ import annotations

import uuid
from datetime import date, datetime

from evidentia_core.domain.taxonomy import DEFAULT_PRESET, Activity
from pydantic import Field, model_validator

from evidentia_api.schemas.common import ApiModel


class ProjectCreate(ApiModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    starts_on: date | None = None
    ends_on: date | None = None
    taxonomy_preset: str = DEFAULT_PRESET

    @model_validator(mode="after")
    def _dates(self) -> ProjectCreate:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("ends_on must be on or after starts_on")
        return self


class ProjectUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    starts_on: date | None = None
    ends_on: date | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class ProjectStats(ApiModel):
    assets_total: int = 0
    by_state: dict[str, int] = Field(default_factory=dict)
    sites: int = 0


class ProjectOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    starts_on: date | None
    ends_on: date | None
    taxonomy_preset: str
    active_taxonomy_version: int
    created_at: datetime
    stats: ProjectStats | None = None


class SiteCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=2000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int = Field(default=1000, ge=10, le=100_000)

    @model_validator(mode="after")
    def _both_or_neither(self) -> SiteCreate:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class SiteUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=10, le=100_000)


class SiteOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    code: str
    description: str | None
    latitude: float | None
    longitude: float | None
    radius_m: int
    created_at: datetime


class TaxonomyOut(ApiModel):
    project_id: uuid.UUID
    version: int
    activities: list[Activity]
    created_at: datetime


class TaxonomyUpdate(ApiModel):
    activities: list[Activity] = Field(min_length=1, max_length=40)


class TaxonomyPresetOut(ApiModel):
    name: str
    activities: list[Activity]
