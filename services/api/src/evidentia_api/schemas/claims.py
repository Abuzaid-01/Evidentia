from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from evidentia_core.domain.enums import (
    ClaimStatus,
    ClaimType,
    EvidenceRelation,
    MetricSource,
    SupportLevel,
    ValidationVerdict,
)
from pydantic import Field, model_validator

from evidentia_api.schemas.common import ApiModel

# --- metrics ---------------------------------------------------------------------------------


class MetricCreate(ApiModel):
    name: str = Field(min_length=2, max_length=200)
    value: Decimal
    unit: str | None = Field(default=None, max_length=40)
    method: str = Field(min_length=3, max_length=2000, description="How it was measured")
    source_type: MetricSource
    source_reference: str = Field(
        min_length=2, max_length=2000, description="Form id, document, sensor..."
    )
    site_id: uuid.UUID | None = None
    period_start: date | None = None
    period_end: date | None = None


class MetricOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    name: str
    value: Decimal
    unit: str | None
    method: str
    source_type: MetricSource
    source_reference: str
    period_start: date | None
    period_end: date | None
    created_at: datetime


# --- claims ---------------------------------------------------------------------------------


class ClaimCreate(ApiModel):
    statement: str = Field(min_length=5, max_length=2000)
    claim_type: ClaimType
    site_id: uuid.UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    supersedes_id: uuid.UUID | None = None


class ClaimUpdate(ApiModel):
    statement: str | None = Field(default=None, min_length=5, max_length=2000)
    claim_type: ClaimType | None = None
    site_id: uuid.UUID | None = None
    period_start: date | None = None
    period_end: date | None = None


class EvidenceLinkCreate(ApiModel):
    asset_id: uuid.UUID | None = Field(
        default=None, description="Required unless pair_id is given (then the after photo is used)"
    )
    derivative_id: uuid.UUID | None = None
    observation_id: uuid.UUID | None = None
    pair_id: uuid.UUID | None = Field(
        default=None, description="A confirmed before/after comparison (Phase 7)"
    )
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS
    span: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _target(self) -> EvidenceLinkCreate:
        if self.asset_id is None and self.pair_id is None:
            raise ValueError("Give an asset_id or a pair_id")
        if self.pair_id is not None and self.observation_id is not None:
            raise ValueError("Link either an observation or a before/after pair, not both")
        return self


class EvidenceLinkOut(ApiModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    observation_id: uuid.UUID | None
    pair_id: uuid.UUID | None = None
    relation: EvidenceRelation
    span: dict[str, Any] | None
    note: str | None
    created_at: datetime
    # resolved for display
    verified: bool = False
    observation_summary: str | None = None
    pair_summary: str | None = None
    asset_caption: str | None = None
    thumb_url: str | None = None


class DecisionBody(ApiModel):
    note: str | None = Field(default=None, max_length=2000)
    override: bool = Field(
        default=False, description="Approve despite a not_supported LLM verdict (needs note)"
    )

    @model_validator(mode="after")
    def _override_needs_note(self) -> DecisionBody:
        if self.override and not (self.note and self.note.strip()):
            raise ValueError("An override needs a note explaining why")
        return self


class ClaimOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    statement: str
    claim_type: ClaimType
    status: ClaimStatus
    support_level: SupportLevel
    period_start: date | None
    period_end: date | None
    rule_check: dict[str, Any] | None
    validation: dict[str, Any] | None
    validation_verdict: ValidationVerdict | None
    validated_at: datetime | None
    created_by_id: uuid.UUID | None
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    supersedes_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ClaimDetail(ClaimOut):
    evidence: list[EvidenceLinkOut]
    metrics: list[MetricOut]


class GraphNode(ApiModel):
    id: str
    type: str  # claim | metric | observation | asset | event | before_after
    label: str
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(ApiModel):
    source: str
    target: str
    relation: str


class EvidenceGraph(ApiModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# --- activity events -----------------------------------------------------------------------------


class EventCreate(ApiModel):
    activity: str = Field(min_length=2, max_length=48)
    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    site_id: uuid.UUID | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class EventOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    activity: str
    title: str
    description: str | None
    starts_on: date | None
    ends_on: date | None
    evidence_count: int = 0
    created_at: datetime


class EventSuggestion(ApiModel):
    activity: str
    activity_label: str
    site_id: uuid.UUID | None
    site_name: str | None
    starts_on: date | None
    ends_on: date | None
    asset_ids: list[uuid.UUID]
    verified_observations: int
    suggested_title: str
