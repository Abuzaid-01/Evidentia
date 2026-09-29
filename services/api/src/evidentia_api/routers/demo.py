"""Demo mode: one-click versions of the evidence workflow for live presentations (all calls real)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from evidentia_api.deps import Contributor, Manager, RequestId, SettingsDep, TenantDB
from evidentia_api.schemas.demo import DemoClaimIn, DemoClaimOut, DemoReportIn, DemoReportOut
from evidentia_api.services import demo as svc
from evidentia_api.services.projects import get_project

router = APIRouter(prefix="/v1/demo", tags=["demo"])


def _ready(request: Request) -> bool:
    return request.app.state.cloudinary is not None


@router.post("/assets/{asset_id}/claim", response_model=DemoClaimOut)
async def claim_from_photo(
    asset_id: uuid.UUID,
    principal: Contributor,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
    body: DemoClaimIn | None = None,
) -> DemoClaimOut:
    """Photo -> verified observations -> claim with linked evidence -> AI-validated -> approved by
    the separate Demo reviewer. A claim the validator rejects is left in review."""
    svc.require_enabled(settings)
    return await svc.make_claim(
        db,
        principal,
        asset_id,
        body or DemoClaimIn(),
        settings,
        request.app.state.text_llms,
        cloudinary_ready=_ready(request),
        rid=rid,
    )


@router.post("/claims/{claim_id}/approve", response_model=DemoClaimOut)
async def fast_track(
    claim_id: uuid.UUID,
    principal: Contributor,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
) -> DemoClaimOut:
    """An existing claim: validate, submit and have the Demo reviewer approve it."""
    svc.require_enabled(settings)
    return await svc.fast_track_claim(
        db,
        principal,
        claim_id,
        settings,
        request.app.state.text_llms,
        cloudinary_ready=_ready(request),
        rid=rid,
    )


@router.post("/projects/{project_id}/report", response_model=DemoReportOut)
async def report(
    project_id: uuid.UUID,
    principal: Manager,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
    body: DemoReportIn | None = None,
) -> DemoReportOut:
    """Every approved claim -> report -> cited narrative -> published snapshot + PDF."""
    svc.require_enabled(settings)
    await get_project(db, project_id)
    return await svc.publish_report(
        db,
        principal,
        project_id,
        body or DemoReportIn(),
        settings,
        request.app.state.text_llms,
        cloudinary_ready=_ready(request),
        rid=rid,
    )
