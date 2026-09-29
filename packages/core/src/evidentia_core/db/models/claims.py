"""Phase 4: human review decisions, metrics, claims, activity events and the evidence links
that connect them to assets/observations (the evidence graph)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk
from evidentia_core.domain.enums import (
    ClaimStatus,
    ClaimType,
    EvidenceRelation,
    EvidenceTarget,
    MetricSource,
    ReviewDecision,
    SupportLevel,
    ValidationVerdict,
)


class ObservationReview(UUIDPk, TenantScoped, Timestamps, Base):
    """One reviewer decision. Observations are never edited in place: an edit creates a new
    human observation that supersedes the AI one, and this row links them."""

    __tablename__ = "observation_reviews"

    observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observations.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[ReviewDecision]
    previous_status: Mapped[str] = mapped_column(String(20))
    replacement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("observations.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)


class Metric(UUIDPk, TenantScoped, Timestamps, Base):
    """A measured value with a declared source. Reports may only state numbers that exist here."""

    __tablename__ = "metrics"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    value: Mapped[float] = mapped_column(Numeric(18, 4))
    unit: Mapped[str | None] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(Text)
    source_type: Mapped[MetricSource]
    source_reference: Mapped[str] = mapped_column(Text)  # form id, document, sensor, URL...
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Claim(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "claims"
    __table_args__ = (Index("ix_claims_project_status", "project_id", "status"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    statement: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[ClaimType]
    status: Mapped[ClaimStatus] = mapped_column(default=ClaimStatus.DRAFT)
    support_level: Mapped[SupportLevel] = mapped_column(default=SupportLevel.UNSUPPORTED)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    rule_check: Mapped[dict[str, Any] | None]  # deterministic support rules result
    validation: Mapped[dict[str, Any] | None]  # LLM validation result (verdict, reasoning, model)
    validation_verdict: Mapped[ValidationVerdict | None]
    validated_at: Mapped[datetime | None]
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None]
    decision_note: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL")
    )


class ClaimMetric(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "claim_metrics"
    __table_args__ = (Index("uq_claim_metrics_pair", "claim_id", "metric_id", unique=True),)

    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    metric_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("metrics.id", ondelete="RESTRICT"))


class ActivityEvent(UUIDPk, TenantScoped, Timestamps, Base):
    """A real-world activity/phase (e.g. 'Pipe installation, Site A, 4-26 Aug') assembled from
    verified observations."""

    __tablename__ = "activity_events"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    activity: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class EvidenceLink(UUIDPk, TenantScoped, Timestamps, Base):
    """Edge of the evidence graph: (claim | event) <- asset [observation] [video span] [pair]."""

    __tablename__ = "evidence_links"
    __table_args__ = (
        Index("ix_evidence_links_target", "target_type", "target_id"),
        Index("ix_evidence_links_asset", "asset_id"),
        CheckConstraint(
            "(target_type = 'claim' AND claim_id IS NOT NULL AND event_id IS NULL) OR "
            "(target_type = 'event' AND event_id IS NOT NULL AND claim_id IS NULL)",
            name="one_target",
        ),
    )

    target_type: Mapped[EvidenceTarget]
    target_id: Mapped[uuid.UUID]
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activity_events.id", ondelete="CASCADE")
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("observations.id", ondelete="RESTRICT")
    )
    relation: Mapped[EvidenceRelation] = mapped_column(default=EvidenceRelation.SUPPORTS)
    span: Mapped[dict[str, Any] | None]  # e.g. {"start_ms": 21000, "end_ms": 37000} (Phase 6)
    # Phase 7: a confirmed before/after comparison (asset_id is then the pair's after photo)
    pair_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("before_after_pairs.id", ondelete="RESTRICT"), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
