"""Schemas for project observability, ingestion health, and AI cost accounting (PLAN Phase 9)."""

from __future__ import annotations

import uuid

from pydantic import Field

from evidentia_api.schemas.common import ApiModel


class CostBreakdown(ApiModel):
    cloudinary_transformations_usd: float = 0.0
    cloudinary_storage_usd: float = 0.0
    llm_tokens_usd: float = 0.0
    embedding_compute_usd: float = 0.0
    total_estimated_usd: float = 0.0
    currency: str = "USD"


class IngestionHealth(ApiModel):
    total_assets: int = 0
    state_counts: dict[str, int] = Field(default_factory=dict)
    failure_rate_pct: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    total_analysis_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0


class VerificationHealth(ApiModel):
    claims_total: int = 0
    claims_by_status: dict[str, int] = Field(default_factory=dict)
    observations_total: int = 0
    observations_verified: int = 0
    verification_rate_pct: float = 0.0


class ActivityMetric(ApiModel):
    activity: str
    asset_count: int = 0
    verified_count: int = 0


class ProjectAnalyticsOut(ApiModel):
    project_id: uuid.UUID
    ingestion: IngestionHealth
    costs: CostBreakdown
    verification: VerificationHealth
    activities: list[ActivityMetric]
