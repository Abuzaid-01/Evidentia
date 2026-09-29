from __future__ import annotations

import uuid
from typing import Any

from evidentia_core.db.models import Report
from fastapi import APIRouter, Request, status
from sqlalchemy import select

from evidentia_api.deps import Contributor, Manager, RequestId, SettingsDep, TenantDB, Viewer
from evidentia_api.schemas.reports import (
    DownloadLink,
    NarrativeIn,
    RenderedReport,
    ReportCreate,
    ReportDetail,
    ReportOut,
    ReportUpdate,
    SnapshotOut,
    SnapshotVerification,
)
from evidentia_api.services import reports as svc
from evidentia_api.services.projects import get_project

router = APIRouter(prefix="/v1", tags=["reports"])


def _ready(request: Request) -> bool:
    return request.app.state.cloudinary is not None


@router.get("/projects/{project_id}/reports", response_model=list[ReportOut])
async def list_reports(project_id: uuid.UUID, _: Viewer, db: TenantDB) -> list[ReportOut]:
    await get_project(db, project_id)
    rows = await db.scalars(
        select(Report).where(Report.project_id == project_id).order_by(Report.created_at.desc())
    )
    return [ReportOut.model_validate(r) for r in rows.all()]


@router.post(
    "/projects/{project_id}/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED
)
async def create_report(
    project_id: uuid.UUID, body: ReportCreate, principal: Contributor, db: TenantDB, rid: RequestId
) -> ReportOut:
    """Without `claim_ids`, every approved claim overlapping the period (and site) is included."""
    return ReportOut.model_validate(await svc.create_report(db, principal, project_id, body, rid))


@router.get("/reports/{report_id}", response_model=ReportDetail)
async def get_report(report_id: uuid.UUID, _: Viewer, db: TenantDB) -> ReportDetail:
    return await svc.report_detail(db, await svc.get_report(db, report_id))


@router.patch("/reports/{report_id}", response_model=ReportOut)
async def update_report(
    report_id: uuid.UUID, body: ReportUpdate, principal: Contributor, db: TenantDB, rid: RequestId
) -> ReportOut:
    return ReportOut.model_validate(await svc.update_report(db, principal, report_id, body, rid))


@router.post("/reports/{report_id}/generate", response_model=ReportDetail)
async def generate(
    report_id: uuid.UUID, principal: Contributor, db: TenantDB, request: Request, rid: RequestId
) -> ReportDetail:
    """Write the narrative from approved claims only. Sentences that fail the citation or number
    checks are dropped and listed in `narrative_meta.rejected`."""
    report = await svc.generate_narrative(
        db, principal, report_id, request.app.state.text_llms, rid
    )
    return await svc.report_detail(db, report)


@router.put("/reports/{report_id}/narrative", response_model=ReportDetail)
async def set_narrative(
    report_id: uuid.UUID, body: NarrativeIn, principal: Contributor, db: TenantDB, rid: RequestId
) -> ReportDetail:
    """Replace the narrative with an edited one. Rejected as a whole if any sentence fails."""
    report = await svc.set_narrative(db, principal, report_id, body, rid)
    return await svc.report_detail(db, report)


@router.get("/reports/{report_id}/preview", response_model=RenderedReport)
async def preview(
    report_id: uuid.UUID, _: Viewer, db: TenantDB, settings: SettingsDep, request: Request
) -> RenderedReport:
    report = await svc.get_report(db, report_id)
    return await svc.preview(db, report, settings, cloudinary_ready=_ready(request))


@router.post(
    "/reports/{report_id}/publish", response_model=SnapshotOut, status_code=status.HTTP_201_CREATED
)
async def publish(
    report_id: uuid.UUID,
    principal: Manager,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
) -> SnapshotOut:
    """Freeze an immutable, hashed snapshot and queue its PDF."""
    return await svc.publish(
        db, principal, report_id, settings, cloudinary_ready=_ready(request), rid=rid
    )


@router.get("/reports/{report_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(report_id: uuid.UUID, _: Viewer, db: TenantDB) -> list[SnapshotOut]:
    await svc.get_report(db, report_id)
    return await svc.list_snapshots(db, report_id)


@router.get("/reports/{report_id}/snapshots/{version}/manifest")
async def manifest(report_id: uuid.UUID, version: int, _: Viewer, db: TenantDB) -> dict[str, Any]:
    """The frozen manifest: claims, evidence, observations with model versions, Cloudinary
    public_ids and transformations, approvers."""
    return (await svc.get_snapshot(db, report_id, version)).manifest


@router.get("/reports/{report_id}/snapshots/{version}/html", response_model=RenderedReport)
async def snapshot_html(
    report_id: uuid.UUID, version: int, _: Viewer, db: TenantDB
) -> RenderedReport:
    snapshot = await svc.get_snapshot(db, report_id, version)
    return RenderedReport(
        html=svc.render_html(snapshot.manifest), manifest_sha256=snapshot.manifest_sha256
    )


@router.get("/reports/{report_id}/snapshots/{version}/verify", response_model=SnapshotVerification)
async def verify(
    report_id: uuid.UUID, version: int, _: Viewer, db: TenantDB
) -> SnapshotVerification:
    """Re-render the stored manifest and compare both hashes with the ones taken at publish."""
    return svc.verify_snapshot(await svc.get_snapshot(db, report_id, version))


@router.get("/reports/{report_id}/snapshots/{version}/pdf", response_model=DownloadLink)
async def pdf(
    report_id: uuid.UUID, version: int, principal: Viewer, db: TenantDB, rid: RequestId
) -> DownloadLink:
    """Short-lived signed download link for the PDF stored privately in Cloudinary (audited)."""
    return await svc.pdf_link(db, principal, await svc.get_snapshot(db, report_id, version), rid)


@router.post("/reports/{report_id}/snapshots/{version}/pdf", response_model=SnapshotOut)
async def rerender_pdf(
    report_id: uuid.UUID,
    version: int,
    principal: Manager,
    db: TenantDB,
    request: Request,
    rid: RequestId,
) -> SnapshotOut:
    """Queue the PDF again (after a failure, or once Cloudinary/Chromium are set up)."""
    snapshot = await svc.get_snapshot(db, report_id, version)
    return await svc.rerender_pdf(
        db, principal, snapshot, cloudinary_ready=_ready(request), rid=rid
    )
