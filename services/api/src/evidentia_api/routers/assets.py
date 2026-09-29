from __future__ import annotations

import uuid

from evidentia_core import tasks
from evidentia_core.db.models import Observation
from evidentia_core.domain.enums import AssetState, ResourceType
from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from evidentia_api.deps import RequestId, Reviewer, SettingsDep, TenantDB, Viewer
from evidentia_api.errors import Unprocessable
from evidentia_api.schemas.assets import (
    AssetDetail,
    AssetSummary,
    MediaUrlOut,
    MediaVariant,
    ReanalyzeOut,
)
from evidentia_api.schemas.campaigns import LineageOut
from evidentia_api.schemas.common import Page
from evidentia_api.services import assets as svc
from evidentia_api.services import audit
from evidentia_api.services import campaigns as campaign_svc
from evidentia_api.services.projects import get_project

router = APIRouter(prefix="/v1", tags=["assets"])

_REANALYZABLE = {AssetState.READY, AssetState.REVIEW_REQUIRED, AssetState.FAILED_PERMANENT}


@router.get("/projects/{project_id}/assets", response_model=Page[AssetSummary])
async def list_assets(
    project_id: uuid.UUID,
    _: Viewer,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    state: AssetState | None = None,
    site_id: uuid.UUID | None = None,
    resource_type: ResourceType | None = None,
    include_pending: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=48, ge=1, le=200),
) -> Page[AssetSummary]:
    await get_project(db, project_id)
    rows, next_cursor = await svc.list_assets(
        db,
        project_id,
        state=state,
        site_id=site_id,
        resource_type=resource_type,
        include_pending=include_pending,
        cursor=cursor,
        limit=limit,
    )
    ready = request.app.state.cloudinary is not None
    return Page(
        items=[svc.to_summary(a, settings, cloudinary_ready=ready) for a in rows],
        next_cursor=next_cursor,
    )


@router.get("/assets/{asset_id}", response_model=AssetDetail)
async def get_asset(
    asset_id: uuid.UUID, _: Viewer, db: TenantDB, settings: SettingsDep, request: Request
) -> AssetDetail:
    asset = await svc.get_asset(db, asset_id)
    return await svc.asset_detail(
        db, asset, settings, cloudinary_ready=request.app.state.cloudinary is not None
    )


@router.get("/assets/{asset_id}/lineage", response_model=LineageOut)
async def asset_lineage(
    asset_id: uuid.UUID,
    _: Viewer,
    db: TenantDB,
    settings: SettingsDep,
) -> LineageOut:
    """Return the complete provenance and transformation lineage for an evidence asset."""
    return await campaign_svc.get_asset_lineage(db, asset_id, settings)


@router.get("/assets/{asset_id}/media", response_model=MediaUrlOut)
async def media_url(
    asset_id: uuid.UUID,
    principal: Viewer,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
    variant: MediaVariant = "review",
    start_ms: int | None = Query(default=None, ge=0),
    end_ms: int | None = Query(default=None, ge=0),
) -> MediaUrlOut:
    if request.app.state.cloudinary is None:
        raise Unprocessable("Cloudinary is not configured")
    asset = await svc.get_asset(db, asset_id)
    url = svc.media_url(asset, variant, settings, start_ms=start_ms, end_ms=end_ms)
    if variant == "clip":
        await svc.record_clip(db, asset, url)
    if variant == "original":  # opening an original is an auditable access to evidence
        audit.record(
            db,
            org_id=principal.org_id,
            principal=principal,
            action="asset.original_accessed",
            target_type="asset",
            target_id=asset.id,
            request_id=rid,
        )
        await db.commit()
    return MediaUrlOut(
        url=url.url,
        variant=url.variant,
        transformation=url.transformation,
        named_transformation=url.named_transformation,
        format=url.format,
        expires_at=url.expires_at,
    )


@router.get("/assets/{asset_id}/chapters.vtt", response_class=PlainTextResponse)
async def chapters(asset_id: uuid.UUID, _: Viewer, db: TenantDB) -> PlainTextResponse:
    """WebVTT chapters built from timestamped video observations."""
    asset = await svc.get_asset(db, asset_id)
    if asset.resource_type != ResourceType.VIDEO:
        raise Unprocessable("Chapters are only available for video")
    rows = (await db.scalars(select(Observation).where(Observation.asset_id == asset.id))).all()
    return PlainTextResponse(svc.chapters_for(list(rows)), media_type="text/vtt")


@router.post("/assets/{asset_id}/reanalyze", response_model=ReanalyzeOut)
async def reanalyze(
    asset_id: uuid.UUID, principal: Reviewer, db: TenantDB, rid: RequestId
) -> ReanalyzeOut:
    """Re-run AI enrichment as a new generation. Previous observations are kept (superseded)."""
    asset = await svc.get_asset(db, asset_id)
    if asset.state not in _REANALYZABLE:
        raise Unprocessable(f"Cannot re-analyse an asset in state '{asset.state.value}'")
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="asset.reanalysis_requested",
        target_type="asset",
        target_id=asset.id,
        data={"from_generation": asset.analysis_generation},
        request_id=rid,
    )
    await db.commit()
    tasks.enqueue(tasks.REANALYZE_ASSET, str(asset.id))
    return ReanalyzeOut(asset_id=asset.id, queued=True)
