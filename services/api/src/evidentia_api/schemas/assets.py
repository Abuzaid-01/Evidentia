from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from evidentia_core.domain.enums import (
    AnalysisTask,
    AssetState,
    ObservationStatus,
    OntologyType,
    ProvenanceSource,
    ResourceType,
    RunStatus,
    SourceKind,
)
from pydantic import Field

from evidentia_api.schemas.common import ApiModel

# --- uploads -------------------------------------------------------------------------------


class UploadSignRequest(ApiModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)
    declared_activity: str | None = Field(default=None, max_length=48)
    captured_at: datetime | None = Field(
        default=None, description="Optional capture time from the device (used if EXIF has none)"
    )
    note: str | None = Field(default=None, max_length=1000)


class UploadSignResponse(ApiModel):
    asset_id: uuid.UUID
    resource_type: ResourceType
    upload_url: str
    fields: dict[str, str]
    chunk_size: int
    expires_at: int


class UploadConfirmRequest(ApiModel):
    public_id: str
    version: int
    signature: str = Field(min_length=10, max_length=128)


# --- assets ----------------------------------------------------------------------------------


class AssetSummary(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    resource_type: ResourceType
    state: AssetState
    state_reason: str | None
    original_filename: str | None
    format: str | None
    bytes: int | None
    width: int | None
    height: int | None
    duration_seconds: float | None
    capture_time: datetime | None
    capture_time_source: ProvenanceSource
    location_source: ProvenanceSource
    declared_activity: str | None
    caption: str | None
    top_activity: str | None
    top_activity_confidence: float | None
    review_priority: float | None
    flags: dict[str, Any] | None
    exact_duplicate_of_id: uuid.UUID | None
    created_at: datetime
    thumb_url: str | None = None


class ObservationOut(ApiModel):
    id: uuid.UUID
    ontology_type: OntologyType
    subject: str
    predicate: str
    value: dict[str, Any] | None
    confidence: float | None
    evidence_span: dict[str, Any] | None
    source_kind: SourceKind
    source_provider: str | None
    status: ObservationStatus
    review_priority: float | None
    review_signals: dict[str, Any] | None
    analysis_run_id: uuid.UUID | None
    generation: int
    created_at: datetime


class AnalysisRunOut(ApiModel):
    id: uuid.UUID
    task: AnalysisTask
    provider: str
    model: str
    model_version: str | None
    prompt_version: str | None
    schema_version: str | None
    taxonomy_version: int | None
    generation: int
    status: RunStatus
    error: str | None
    latency_ms: int | None
    attempts: int
    created_at: datetime
    finished_at: datetime | None


class DerivativeOut(ApiModel):
    id: uuid.UUID
    purpose: str
    named_transformation: str | None
    transformation: str
    format: str | None
    source: str
    generative: bool
    bytes: int | None
    created_at: datetime


class CloudinaryRef(ApiModel):
    public_id: str
    asset_id: str | None
    version: int | None
    asset_folder: str | None
    delivery_type: str


class NearDuplicate(ApiModel):
    asset_id: uuid.UUID
    distance: int


class AssetDetail(AssetSummary):
    uploaded_by_id: uuid.UUID | None
    contributor_note: str | None
    declared_capture_time: datetime | None
    latitude: float | None
    longitude: float | None
    exif: dict[str, Any] | None
    sha256: str | None
    phash_hex: str | None
    quality_score: float | None
    review_reasons: list[Any] | None
    near_duplicates: list[NearDuplicate]
    cloudinary: CloudinaryRef
    observations: list[ObservationOut]
    analysis_runs: list[AnalysisRunOut]
    derivatives: list[DerivativeOut]
    analysis_generation: int
    uploaded_at: datetime | None
    state_changed_at: datetime | None


MediaVariant = Literal["thumb", "review", "original", "stream", "clip"]


class MediaUrlOut(ApiModel):
    url: str
    variant: str
    transformation: str
    named_transformation: str | None
    format: str | None
    expires_at: int | None


class ReanalyzeOut(ApiModel):
    asset_id: uuid.UUID
    queued: bool
