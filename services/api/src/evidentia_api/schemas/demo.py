from __future__ import annotations

import uuid

from evidentia_core.domain.enums import ClaimType, ReportAudience, ValidationVerdict
from pydantic import Field

from evidentia_api.schemas.claims import ClaimDetail
from evidentia_api.schemas.common import ApiModel
from evidentia_api.schemas.reports import SnapshotOut


class DemoClaimIn(ApiModel):
    statement: str | None = Field(
        default=None,
        min_length=5,
        max_length=2000,
        description="Omit to use the photo's AI caption",
    )
    claim_type: ClaimType = ClaimType.DESCRIPTIVE
    metric_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class DemoClaimOut(ApiModel):
    claim: ClaimDetail
    approved: bool
    reviewed_observations: int
    linked_evidence: int
    validation_verdict: ValidationVerdict | None
    reviewer: str
    steps: list[str]
    message: str | None = None


class DemoReportIn(ApiModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    audience: ReportAudience = ReportAudience.INTERNAL


class DemoReportOut(ApiModel):
    report_id: uuid.UUID
    snapshot: SnapshotOut
    claims: int
    narrative_mode: str | None
    sentences: int
    rejected_sentences: int
    steps: list[str]
