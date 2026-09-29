"""Projects, sites (PostGIS) and versioned activity taxonomies."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import Computed, Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk

# Point geography derived from plain lat/lng columns: the app writes floats, PostGIS indexes a point.
POINT_FROM_LATLNG = (
    "CASE WHEN latitude IS NULL OR longitude IS NULL THEN NULL "
    "ELSE (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326))::geography END"
)


class Project(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    taxonomy_preset: Mapped[str] = mapped_column(String(60))
    active_taxonomy_version: Mapped[int] = mapped_column(default=1)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Site(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("project_id", "code"),
        Index("ix_sites_location", "location", postgresql_using="gist"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    radius_m: Mapped[int] = mapped_column(default=1000)
    location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        Computed(POINT_FROM_LATLNG, persisted=True),
        nullable=True,
    )


class Taxonomy(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "taxonomies"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int]
    activities: Mapped[list[Any]]
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
