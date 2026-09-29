"""Pydantic schemas for Campaign Studio, lineage, and external sharing (Phase 8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SocialRenditionOut(BaseModel):
    format: str
    url: str
    transformation: str
    named_transformation: str | None = None
    generative: bool = False
    purpose: str


class CampaignCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    headline: str = Field(min_length=2, max_length=300)
    stat_text: str | None = Field(default=None, max_length=200)
    brand_tag: str | None = Field(default="EVIDENTIA VERIFIED", max_length=100)
    asset_id: uuid.UUID
    pair_id: uuid.UUID | None = None
    claim_id: uuid.UUID | None = None
    metric_id: uuid.UUID | None = None
    formats: list[str] = Field(default=["1:1", "4:5", "9:16", "16:9"])
    generative_fill: bool = False
    generative_restore: bool = False
    redact: bool = True


class CampaignOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    headline: str
    stat_text: str | None
    brand_tag: str | None
    asset_id: uuid.UUID
    pair_id: uuid.UUID | None
    claim_id: uuid.UUID | None
    metric_id: uuid.UUID | None
    formats: list[str]
    generative: bool
    renditions: dict[str, SocialRenditionOut]
    created_at: datetime


class VideoReelSegmentIn(BaseModel):
    asset_id: uuid.UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    caption: str | None = None


class VideoReelCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    segments: list[VideoReelSegmentIn] = Field(min_length=1, max_length=20)
    redact: bool = True


class VideoReelOut(BaseModel):
    id: uuid.UUID
    title: str
    url: str
    transformation: str
    segments_count: int
    duration_seconds: float
    created_at: datetime


class ShareLinkCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    target_type: Literal["report", "evidence", "campaign"]
    target_id: uuid.UUID
    expires_in_days: int = Field(default=7, ge=1, le=90)


class ShareLinkOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    token: str
    title: str
    target_type: str
    target_id: uuid.UUID
    share_url: str
    expires_at: datetime
    view_count: int
    is_revoked: bool
    created_at: datetime


class LineageDerivativeOut(BaseModel):
    id: uuid.UUID
    purpose: str
    named_transformation: str | None = None
    transformation: str
    format: str | None = None
    source: str
    generative: bool
    url: str
    created_at: datetime


class LineageOut(BaseModel):
    asset_id: uuid.UUID
    original_filename: str | None
    public_id: str
    format: str | None
    bytes: int | None
    sha256: str | None
    phash: str | None
    capture_time: datetime | None
    capture_time_source: str
    uploaded_at: datetime | None
    derivatives: list[LineageDerivativeOut]
    pairs: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    campaigns: list[dict[str, Any]]


class SharedContentOut(BaseModel):
    token: str
    title: str
    target_type: str
    project_name: str
    expires_at: datetime
    data: dict[str, Any]
    lineage: list[dict[str, Any]]
