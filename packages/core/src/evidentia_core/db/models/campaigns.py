"""Phase 8: Campaign Studio assets and external read-only share links."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk


class Campaign(UUIDPk, TenantScoped, Timestamps, Base):
    """A collection of social and external media assets generated for a project/claim."""

    __tablename__ = "campaigns"
    __table_args__ = (Index("ix_campaigns_project_created", "project_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    headline: Mapped[str] = mapped_column(String(300))
    stat_text: Mapped[str | None] = mapped_column(String(200))
    brand_tag: Mapped[str | None] = mapped_column(String(100))

    # Evidence source: single asset or confirmed before/after comparison
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    pair_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("before_after_pairs.id", ondelete="SET NULL")
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id", ondelete="SET NULL"))
    metric_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("metrics.id", ondelete="SET NULL")
    )

    formats: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    generative: Mapped[bool] = mapped_column(Boolean, default=False)
    # Mapping of format -> {url, transformation, generative, purpose, format}
    renditions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class ShareLink(UUIDPk, TenantScoped, Timestamps, Base):
    """An external, read-only, expiring share link for verified reports or evidence."""

    __tablename__ = "share_links"
    __table_args__ = (
        Index("ix_share_links_token", "token", unique=True),
        Index("ix_share_links_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    target_type: Mapped[str] = mapped_column(String(32))  # "report", "evidence", "campaign"
    target_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime]
    view_count: Mapped[int] = mapped_column(default=0)
    last_viewed_at: Mapped[datetime | None]
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
