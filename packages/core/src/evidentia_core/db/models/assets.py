"""Our canonical record for every Cloudinary media asset, plus derived versions (lineage)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import BigInteger, Computed, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk
from evidentia_core.db.models.projects import POINT_FROM_LATLNG
from evidentia_core.domain.enums import AssetState, ProvenanceSource, ResourceType


class Asset(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_project_state", "project_id", "state"),
        Index("ix_assets_project_capture", "project_id", "capture_time"),
        Index("ix_assets_org_sha256", "organization_id", "sha256"),
        Index("ix_assets_project_phash", "project_id", "phash"),
        Index("ix_assets_location", "location", postgresql_using="gist"),
        Index("ix_assets_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    # --- ownership & declared context (from the upload form) -------------------
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    declared_activity: Mapped[str | None] = mapped_column(String(48))
    declared_capture_time: Mapped[datetime | None]
    contributor_note: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(512))
    declared_mime: Mapped[str | None] = mapped_column(String(100))
    declared_bytes: Mapped[int | None] = mapped_column(BigInteger)

    # --- Cloudinary identity -----------------------------------------------------
    resource_type: Mapped[ResourceType]
    delivery_type: Mapped[str] = mapped_column(String(20), default="authenticated")
    public_id: Mapped[str] = mapped_column(String(255), unique=True)
    cloudinary_asset_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    cloudinary_version: Mapped[int | None] = mapped_column(BigInteger)
    asset_folder: Mapped[str | None] = mapped_column(String(512))

    # --- technical metadata ----------------------------------------------------------
    format: Mapped[str | None] = mapped_column(String(16))
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None]
    height: Mapped[int | None]
    duration_seconds: Mapped[float | None]
    etag: Mapped[str | None] = mapped_column(String(64))
    sha256: Mapped[str | None] = mapped_column(String(64))
    phash: Mapped[int | None] = mapped_column(BigInteger)  # 64-bit perceptual hash (signed)
    uploaded_at: Mapped[datetime | None]

    # --- provenance --------------------------------------------------------------------
    capture_time: Mapped[datetime | None]
    capture_time_source: Mapped[ProvenanceSource] = mapped_column(default=ProvenanceSource.NONE)
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    location_source: Mapped[ProvenanceSource] = mapped_column(default=ProvenanceSource.NONE)
    location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        Computed(POINT_FROM_LATLNG, persisted=True),
        nullable=True,
    )
    exif: Mapped[dict[str, Any] | None]  # curated subset, raw is in media_metadata
    media_metadata: Mapped[dict[str, Any] | None]

    # --- pipeline -------------------------------------------------------------------------
    state: Mapped[AssetState] = mapped_column(default=AssetState.AWAITING_UPLOAD)
    state_reason: Mapped[str | None] = mapped_column(Text)
    state_changed_at: Mapped[datetime | None]
    analysis_generation: Mapped[int] = mapped_column(default=1)

    # --- intelligence summary (denormalised for fast lists) ----------------------------------
    caption: Mapped[str | None] = mapped_column(Text)
    top_activity: Mapped[str | None] = mapped_column(String(48))
    top_activity_confidence: Mapped[float | None]
    quality_score: Mapped[float | None]
    flags: Mapped[dict[str, Any] | None]  # people_present, sensitive, text_present, inconsistencies
    review_priority: Mapped[float | None]
    review_reasons: Mapped[list[Any] | None]
    exact_duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    near_duplicates: Mapped[list[Any] | None]  # [{asset_id, distance}]

    # --- search (Phase 3) ---------------------------------------------------------------------
    search_text: Mapped[str | None] = mapped_column(
        Text
    )  # built from observations (see search_doc)
    search_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(search_text, ''))", persisted=True),
        nullable=True,
    )
    verified_activities: Mapped[list[Any] | None]  # activity keys with a VERIFIED observation
    reviewed_at: Mapped[datetime | None]
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Derivative(UUIDPk, TenantScoped, Timestamps, Base):
    """A derived rendition of an asset. Records the exact transformation for traceability."""

    __tablename__ = "derivatives"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(40))  # thumb, review, ai, public_redacted, ...
    named_transformation: Mapped[str | None] = mapped_column(String(80))
    transformation: Mapped[str] = mapped_column(Text)
    format: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(20))  # eager | on_demand
    generative: Mapped[bool] = mapped_column(default=False)
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
