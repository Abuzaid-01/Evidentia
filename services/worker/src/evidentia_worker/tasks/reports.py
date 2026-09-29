"""Render a published report snapshot to PDF and store it privately in Cloudinary.

The PDF is printed from the same pure HTML render the API hashed at publish time, so the PDF always
matches the snapshot's manifest. The snapshot row itself is immutable except for the pdf_* columns.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import structlog
from evidentia_cloudinary import admin
from evidentia_cloudinary.errors import CloudinaryPermanentError
from evidentia_cloudinary.upload import report_pdf_path
from evidentia_core import tasks
from evidentia_core.db.models import Report, ReportSnapshot
from evidentia_core.db.session import sync_system_session
from evidentia_core.domain.enums import PdfStatus
from evidentia_reporting import PdfRendererUnavailable, html_to_pdf, render_html

from evidentia_worker.celery_app import app
from evidentia_worker.context import get_context
from evidentia_worker.errors import TRANSIENT_EXCEPTIONS

log = structlog.get_logger("evidentia.reports")


def _finish(snapshot_id: uuid.UUID, status: PdfStatus, **values: object) -> None:
    with sync_system_session() as session:
        snapshot = session.get(ReportSnapshot, snapshot_id)
        if snapshot is None:
            return
        snapshot.pdf_status = status
        for key, value in values.items():
            setattr(snapshot, key, value)
        session.commit()


@app.task(
    name=tasks.RENDER_REPORT_PDF,
    bind=True,
    max_retries=4,
    autoretry_for=TRANSIENT_EXCEPTIONS,
    retry_backoff=True,
)
def render_report_pdf(self, snapshot_id: str) -> str:  # type: ignore[no-untyped-def]
    ctx = get_context()
    sid = uuid.UUID(snapshot_id)
    with sync_system_session() as session:
        snapshot = session.get(ReportSnapshot, sid)
        if snapshot is None:
            return "missing"
        if snapshot.pdf_status == PdfStatus.READY:
            return "ready"
        report = session.get(Report, snapshot.report_id)
        assert report is not None  # FK
        manifest, version = snapshot.manifest, snapshot.version
        org_id, project_id, report_id = report.organization_id, report.project_id, report.id

    if ctx.creds is None:
        _finish(sid, PdfStatus.SKIPPED, pdf_error="Cloudinary is not configured (CLOUDINARY_URL)")
        return "skipped"
    try:
        pdf = html_to_pdf(render_html(manifest))
    except PdfRendererUnavailable as exc:
        _finish(sid, PdfStatus.FAILED, pdf_error=str(exc))
        log.error("report_pdf_renderer_unavailable", snapshot_id=snapshot_id, error=str(exc))
        return "failed"

    folder, public_id = report_pdf_path(
        ctx.settings.cloudinary_folder_root, org_id, project_id, report_id, version
    )
    try:
        admin.upload_authenticated_raw(
            pdf,
            public_id,
            asset_folder=folder,
            tags=["evidentia", "evidentia_report"],
            context={"ev_report": str(report_id), "ev_version": str(version)},
        )
    except CloudinaryPermanentError as exc:
        _finish(sid, PdfStatus.FAILED, pdf_error=f"Cloudinary rejected the upload: {exc}")
        return "failed"
    _finish(
        sid,
        PdfStatus.READY,
        pdf_public_id=public_id,
        pdf_bytes=len(pdf),
        pdf_sha256=hashlib.sha256(pdf).hexdigest(),
        pdf_error=None,
        pdf_rendered_at=datetime.now(UTC),
    )
    log.info("report_pdf_ready", snapshot_id=snapshot_id, bytes=len(pdf), public_id=public_id)
    return "ready"
