from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from evidentia_core.domain.enums import OntologyType, ReviewDecision
from pydantic import Field, model_validator

from evidentia_api.schemas.assets import AssetSummary
from evidentia_api.schemas.common import ApiModel


class ObservationEdit(ApiModel):
    subject: str | None = Field(default=None, max_length=120)
    predicate: str | None = Field(default=None, max_length=60)
    value: dict[str, Any] | None = None


class DecisionIn(ApiModel):
    observation_id: uuid.UUID
    decision: ReviewDecision
    edit: ObservationEdit | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _edit_needs_payload(self) -> DecisionIn:
        if self.decision == ReviewDecision.EDIT and not self.edit:
            raise ValueError("an 'edit' decision needs an `edit` payload")
        return self


class ReviewRequest(ApiModel):
    decisions: list[DecisionIn] = Field(default_factory=list, max_length=200)
    complete: bool = Field(default=False, description="Mark the asset reviewed (moves it to READY)")
    note: str | None = Field(default=None, max_length=2000)


class ReviewResult(ApiModel):
    asset_id: uuid.UUID
    state: str
    applied: int
    verified_activities: list[str]
    replacements: dict[str, uuid.UUID] = Field(
        default_factory=dict
    )  # old obs id -> new human obs id


class HumanObservationIn(ApiModel):
    ontology_type: OntologyType
    subject: str = Field(min_length=1, max_length=120)
    predicate: str = Field(default="depicted", max_length=60)
    value: dict[str, Any] | None = None
    evidence_span: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=2000)


class QueueItem(ApiModel):
    asset: AssetSummary
    pending_observations: int
    review_reasons: list[Any]


class ReviewHistoryItem(ApiModel):
    id: uuid.UUID
    observation_id: uuid.UUID
    reviewer_id: uuid.UUID
    decision: ReviewDecision
    previous_status: str
    replacement_id: uuid.UUID | None
    note: str | None
    created_at: datetime
