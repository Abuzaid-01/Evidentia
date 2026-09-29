from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from evidentia_core.domain.before_after import (
    DEFAULT_MAX_DISTANCE_M,
    DEFAULT_PER_ANCHOR,
    MIN_GAP_DAYS,
)
from evidentia_core.domain.enums import ClaimStatus, PairOrigin, PairStatus, ProvenanceSource
from pydantic import Field, model_validator

from evidentia_api.schemas.common import ApiModel


class PairPhoto(ApiModel):
    id: uuid.UUID
    original_filename: str | None
    caption: str | None
    capture_time: datetime | None
    capture_time_source: ProvenanceSource
    site_id: uuid.UUID | None
    width: int | None
    height: int | None
    thumb_url: str | None = None


class PairSummary(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    status: PairStatus
    origin: PairOrigin
    before: PairPhoto
    after: PairPhoto
    similarity: float | None
    distance_m: float | None
    days_apart: int | None
    rank_score: float
    alignment_grade: Literal["strong", "partial", "none"] | None = Field(
        description="None until analysed"
    )
    change_summary: str | None
    changed_share: float | None
    green_delta_pp: float | None
    limitation_count: int
    analysis_error: str | None
    decided_at: datetime | None
    created_at: datetime


class PairClaimRef(ApiModel):
    id: uuid.UUID
    statement: str
    status: ClaimStatus


class PairDetail(PairSummary):
    alignment: dict[str, Any] | None
    changes: dict[str, Any] | None
    limitations: list[str]
    analysis_version: str | None
    analyzed_at: datetime | None
    before_url: str | None = Field(description="Signed review rendition of the before photo")
    after_url: str | None
    composite_url: str | None = Field(description="Signed Cloudinary side-by-side composite")
    composite_transformation: str | None
    public_composite_url: str | None = Field(description="Face-pixelated composite (external use)")
    public_composite_transformation: str | None
    created_by_id: uuid.UUID | None
    decided_by_id: uuid.UUID | None
    decision_note: str | None
    claims: list[PairClaimRef] = Field(default_factory=list)


class SuggestRequest(ApiModel):
    site_id: uuid.UUID | None = None
    baseline_from: date | None = None
    baseline_to: date | None = None
    endline_from: date | None = None
    endline_to: date | None = None
    anchor_asset_id: uuid.UUID | None = Field(
        default=None, description="Find 'before' photos for this 'after' photo only"
    )
    max_distance_m: float = Field(default=DEFAULT_MAX_DISTANCE_M, gt=0, le=5000)
    min_gap_days: int = Field(default=MIN_GAP_DAYS, ge=1, le=3650)
    per_anchor: int = Field(default=DEFAULT_PER_ANCHOR, ge=1, le=10)
    limit: int = Field(default=60, ge=1, le=200)

    @model_validator(mode="after")
    def _ordered(self) -> SuggestRequest:
        for start, end in (
            (self.baseline_from, self.baseline_to),
            (self.endline_from, self.endline_to),
        ):
            if start and end and end < start:
                raise ValueError("A window must end on or after its start")
        return self


class Windows(ApiModel):
    baseline_from: date | None
    baseline_to: date | None
    endline_from: date | None
    endline_to: date | None


class SuggestOut(ApiModel):
    windows: Windows | None
    anchors: int = Field(description="After photos that found at least one candidate")
    created: int
    queued: int
    pairs: list[PairSummary]


class PairCreate(ApiModel):
    before_asset_id: uuid.UUID
    after_asset_id: uuid.UUID

    @model_validator(mode="after")
    def _distinct(self) -> PairCreate:
        if self.before_asset_id == self.after_asset_id:
            raise ValueError("Pick two different photos")
        return self


class PairDecision(ApiModel):
    note: str | None = Field(default=None, max_length=2000)
