"""Phase 5: reports (editable drafts) and report snapshots (immutable, published versions)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk
from evidentia_core.domain.enums import PdfStatus, ReportAudience, ReportStatus


class Report(UUIDPk, TenantScoped, Timestamps, Base):
    """The working copy. Only approved claims can be included; publishing freezes a snapshot."""

    __tablename__ = "reports"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    audience: Mapped[ReportAudience] = mapped_column(default=ReportAudience.INTERNAL)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    claim_ids: Mapped[list[Any]] = mapped_column(default=list)  # included claim ids (str)
    # {summary: [{text, cites: [{type, id}]}], overview: [...]} (see domain/reports.py)
    narrative: Mapped[dict[str, Any] | None]
    narrative_meta: Mapped[dict[str, Any] | None]  # generator, prompt, rejected sentences, editor
    status: Mapped[ReportStatus] = mapped_column(default=ReportStatus.DRAFT)
    latest_version: Mapped[int] = mapped_column(default=0)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None]


class ReportSnapshot(UUIDPk, TenantScoped, Timestamps, Base):
    """A published version. The manifest and hashes can never change (enforced by a DB trigger);
    only the PDF columns are filled in later by the worker."""

    __tablename__ = "report_snapshots"
    __table_args__ = (UniqueConstraint("report_id", "version"),)

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int]
    manifest: Mapped[dict[str, Any]]
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    html_sha256: Mapped[str] = mapped_column(String(64))
    renderer_version: Mapped[str] = mapped_column(String(60))
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime]

    pdf_status: Mapped[PdfStatus] = mapped_column(default=PdfStatus.PENDING)
    pdf_public_id: Mapped[str | None] = mapped_column(String(512))
    pdf_bytes: Mapped[int | None] = mapped_column(BigInteger)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    pdf_error: Mapped[str | None] = mapped_column(Text)
    pdf_rendered_at: Mapped[datetime | None]
