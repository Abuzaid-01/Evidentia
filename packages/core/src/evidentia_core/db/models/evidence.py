"""Observations: typed, versioned statements about what a piece of media appears to show."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk
from evidentia_core.domain.enums import ObservationStatus, OntologyType, SourceKind


class Observation(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observations_review", "organization_id", "status", "review_priority"),
        Index("ix_observations_asset_type", "asset_id", "ontology_type"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), index=True
    )
    generation: Mapped[int] = mapped_column(default=1)

    ontology_type: Mapped[OntologyType]
    subject: Mapped[str] = mapped_column(String(120))  # e.g. pipe_installation, water_tank
    predicate: Mapped[str] = mapped_column(String(60))  # e.g. depicted, visible, partially_built
    value: Mapped[dict[str, Any] | None]
    confidence: Mapped[float | None]
    evidence_span: Mapped[dict[str, Any] | None]  # {type: bbox|frame|segment, ...}

    source_kind: Mapped[SourceKind]
    source_provider: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[ObservationStatus] = mapped_column(default=ObservationStatus.PROPOSED)
    review_priority: Mapped[float | None]
    review_signals: Mapped[dict[str, Any] | None]
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None]
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("observations.id", ondelete="SET NULL")
    )
