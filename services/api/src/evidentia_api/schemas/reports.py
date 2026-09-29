from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from evidentia_core.domain.enums import (
    CitationKind,
    ClaimStatus,
    ClaimType,
    PdfStatus,
    ReportAudience,
    ReportStatus,
    SupportLevel,
)
from pydantic import ConfigDict, Field, model_validator

from evidentia_api.schemas.common import ApiModel


class _Period(ApiModel):
    period_start: date | None = None
    period_end: date | None = None

    @model_validator(mode="after")
    def _order(self) -> _Period:
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class ReportCreate(_Period):
    title: str = Field(min_length=3, max_length=300)
    site_id: uuid.UUID | None = None
    audience: ReportAudience = ReportAudience.INTERNAL
    claim_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=200,
        description="Approved claims to include. Omit to include every approved claim in the period.",
    )


class ReportUpdate(_Period):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    site_id: uuid.UUID | None = None
    audience: ReportAudience | None = None
    claim_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class CitationIn(ApiModel):
    type: CitationKind
    id: uuid.UUID


class SentenceIn(ApiModel):
    text: str = Field(min_length=1, max_length=2000)
    cites: list[CitationIn] = Field(default_factory=list, max_length=12)


class NarrativeIn(ApiModel):
    summary: list[SentenceIn] = Field(default_factory=list, max_length=20)
    overview: list[SentenceIn] = Field(default_factory=list, max_length=40)


class SentenceProblemOut(ApiModel):
    section: str
    index: int
    text: str
    problems: list[str]


class ReportOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    title: str
    audience: ReportAudience
    period_start: date | None
    period_end: date | None
    status: ReportStatus
    latest_version: int
    claim_ids: list[uuid.UUID]
    created_by_id: uuid.UUID | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReportClaim(ApiModel):
    id: uuid.UUID
    statement: str
    claim_type: ClaimType
    status: ClaimStatus
    support_level: SupportLevel
    site_id: uuid.UUID | None
    period_start: date | None
    period_end: date | None


class SnapshotOut(ApiModel):
    id: uuid.UUID
    report_id: uuid.UUID
    version: int
    manifest_sha256: str
    html_sha256: str
    renderer_version: str
    published_by_id: uuid.UUID | None
    published_at: datetime
    pdf_status: PdfStatus
    pdf_bytes: int | None
    pdf_error: str | None
    pdf_rendered_at: datetime | None
    # claims in this snapshot that have since been retracted (the snapshot itself never changes)
    retracted_claim_ids: list[uuid.UUID] = Field(default_factory=list)


class ReportDetail(ReportOut):
    narrative: dict[str, Any] | None
    narrative_meta: dict[str, Any] | None
    narrative_problems: list[SentenceProblemOut]
    claims: list[ReportClaim]
    candidate_claims: list[ReportClaim]
    snapshots: list[SnapshotOut]
    warnings: list[str]


class RenderedReport(ApiModel):
    # byte-exact: the html must hash to the snapshot's html_sha256, so never strip whitespace
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=False)

    html: str
    manifest_sha256: str
    problems: list[SentenceProblemOut] = Field(default_factory=list)


class SnapshotVerification(ApiModel):
    version: int
    manifest_sha256: str
    recomputed_manifest_sha256: str
    html_sha256: str
    recomputed_html_sha256: str
    renderer_version: str
    current_renderer_version: str
    identical: bool


class DownloadLink(ApiModel):
    url: str
    expires_at: int | None
