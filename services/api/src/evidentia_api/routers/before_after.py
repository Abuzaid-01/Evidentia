from __future__ import annotations

import uuid

from evidentia_core.domain.enums import PairStatus
from fastapi import APIRouter, Query, Request, status

from evidentia_api.deps import Contributor, RequestId, Reviewer, SettingsDep, TenantDB, Viewer
from evidentia_api.schemas.before_after import (
    PairCreate,
    PairDecision,
    PairDetail,
    PairSummary,
    SuggestOut,
    SuggestRequest,
)
from evidentia_api.services import before_after as svc

router = APIRouter(prefix="/v1", tags=["before-after"])


def _ready(request: Request) -> bool:
    return request.app.state.cloudinary is not None


@router.post("/projects/{project_id}/before-after/suggest", response_model=SuggestOut)
async def suggest(
    project_id: uuid.UUID,
    body: SuggestRequest,
    principal: Contributor,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
) -> SuggestOut:
    """Find before/after candidates: same site, PostGIS distance, baseline vs endline windows,
    ranked by SigLIP similarity. Each new candidate is queued for geometric verification, alignment
    and change detection; the ranking is final once those finish."""
    return await svc.suggest(
        db, principal, project_id, body, settings, cloudinary_ready=_ready(request), rid=rid
    )


@router.get("/projects/{project_id}/before-after", response_model=list[PairSummary])
async def list_pairs(
    project_id: uuid.UUID,
    _: Viewer,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    status_filter: PairStatus | None = None,
    site_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[PairSummary]:
    return await svc.list_pairs(
        db,
        project_id,
        settings,
        cloudinary_ready=_ready(request),
        status=status_filter,
        site_id=site_id,
        asset_id=asset_id,
        limit=limit,
    )


@router.post(
    "/projects/{project_id}/before-after",
    response_model=PairDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_pair(
    project_id: uuid.UUID,
    body: PairCreate,
    principal: Contributor,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
) -> PairDetail:
    """Compare two specific photos (queued for analysis like a suggested pair)."""
    pair = await svc.create_pair(db, principal, project_id, body, rid)
    return await svc.pair_detail(db, pair, settings, cloudinary_ready=_ready(request))


@router.get("/before-after/{pair_id}", response_model=PairDetail)
async def get_pair(
    pair_id: uuid.UUID, _: Viewer, db: TenantDB, settings: SettingsDep, request: Request
) -> PairDetail:
    pair = await svc.get_pair(db, pair_id)
    return await svc.pair_detail(db, pair, settings, cloudinary_ready=_ready(request))


@router.post("/before-after/{pair_id}/analyze", response_model=PairDetail)
async def analyze(
    pair_id: uuid.UUID,
    principal: Reviewer,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
) -> PairDetail:
    """Re-run alignment and change detection (history of decisions is kept)."""
    pair = await svc.reanalyze(db, principal, pair_id, rid)
    return await svc.pair_detail(db, pair, settings, cloudinary_ready=_ready(request))


@router.post("/before-after/{pair_id}/confirm", response_model=PairDetail)
async def confirm(
    pair_id: uuid.UUID,
    body: PairDecision,
    principal: Reviewer,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
) -> PairDetail:
    """A reviewer confirms the photos show the same place: the pair becomes usable as evidence."""
    pair = await svc.decide(db, principal, pair_id, PairStatus.CONFIRMED, body, rid)
    return await svc.pair_detail(db, pair, settings, cloudinary_ready=_ready(request))


@router.post("/before-after/{pair_id}/reject", response_model=PairDetail)
async def reject(
    pair_id: uuid.UUID,
    body: PairDecision,
    principal: Reviewer,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    rid: RequestId,
) -> PairDetail:
    pair = await svc.decide(db, principal, pair_id, PairStatus.REJECTED, body, rid)
    return await svc.pair_detail(db, pair, settings, cloudinary_ready=_ready(request))
