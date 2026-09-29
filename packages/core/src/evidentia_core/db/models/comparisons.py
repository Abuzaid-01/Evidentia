"""Phase 7: before/after pairs. Two photos of the same place on two dates, geometrically verified,
aligned, measured for visible change and, once a reviewer confirms them, usable as claim evidence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk
from evidentia_core.domain.enums import PairOrigin, PairStatus


class BeforeAfterPair(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "before_after_pairs"
    __table_args__ = (
        UniqueConstraint("before_asset_id", "after_asset_id"),
        CheckConstraint("before_asset_id <> after_asset_id", name="distinct_assets"),
        Index("ix_before_after_pairs_project_status", "project_id", "status"),
        Index("ix_before_after_pairs_after", "after_asset_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    before_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    after_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    status: Mapped[PairStatus] = mapped_column(default=PairStatus.CANDIDATE)
    origin: Mapped[PairOrigin]

    # --- candidate generation (SQL: same site, PostGIS distance, windows, pgvector similarity) ---
    similarity: Mapped[float | None]  # SigLIP image-image cosine similarity
    distance_m: Mapped[float | None]  # PostGIS distance between the two capture positions
    days_apart: Mapped[int | None]
    rank_score: Mapped[float] = mapped_column(default=0.0)

    # --- analysis (worker, evidentia_ml.before_after) ------------------------------------------
    alignment: Mapped[dict[str, Any] | None]  # inliers, homography (normalised), shared boxes...
    changes: Mapped[dict[str, Any] | None]  # changed share, green cover, regions...
    change_summary: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[list[Any] | None]  # rule-derived, digit-free sentences
    analysis_version: Mapped[str | None] = mapped_column(String(60))
    analysis_error: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime | None]
    # exact Cloudinary transformation strings (applied to the before asset; the after asset is
    # an l_authenticated layer). Mirrored as derivatives for lineage.
    composite_transformation: Mapped[str | None] = mapped_column(Text)
    public_composite_transformation: Mapped[str | None] = mapped_column(Text)

    # --- human decision ------------------------------------------------------------------------
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None]
    decision_note: Mapped[str | None] = mapped_column(Text)
