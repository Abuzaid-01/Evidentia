from __future__ import annotations

import uuid

from evidentia_core.db.models import ObservationReview
from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select

from evidentia_api.deps import RequestId, Reviewer, SettingsDep, TenantDB, Viewer
from evidentia_api.schemas.assets import ObservationOut
from evidentia_api.schemas.review import (
    HumanObservationIn,
    QueueItem,
    ReviewHistoryItem,
    ReviewRequest,
    ReviewResult,
)
from evidentia_api.services import review as svc
from evidentia_api.services.projects import get_project

router = APIRouter(prefix="/v1", tags=["review"])


@router.get("/projects/{project_id}/review-queue", response_model=list[QueueItem])
async def review_queue(
    project_id: uuid.UUID,
    _: Reviewer,
    db: TenantDB,
    settings: SettingsDep,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[QueueItem]:
    """Assets needing a human, highest review priority first."""
    await get_project(db, project_id)
    return await svc.review_queue(
        db,
        project_id,
        settings,
        cloudinary_ready=request.app.state.cloudinary is not None,
        limit=limit,
    )


@router.post("/assets/{asset_id}/review", response_model=ReviewResult)
async def review_asset(
    asset_id: uuid.UUID,
    body: ReviewRequest,
    principal: Reviewer,
    db: TenantDB,
    settings: SettingsDep,
    rid: RequestId,
) -> ReviewResult:
    """Approve / reject / edit observations (batch, atomic) and optionally complete the review."""
    return await svc.apply_review(db, principal, asset_id, body, settings, rid)


@router.post(
    "/assets/{asset_id}/observations",
    response_model=ObservationOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_observation(
    asset_id: uuid.UUID,
    body: HumanObservationIn,
    principal: Reviewer,
    db: TenantDB,
    settings: SettingsDep,
    rid: RequestId,
) -> ObservationOut:
    """Record something the AI missed (human observation, verified)."""
    obs = await svc.add_human_observation(db, principal, asset_id, body, settings, rid)
    return ObservationOut.model_validate(obs)


@router.get("/assets/{asset_id}/reviews", response_model=list[ReviewHistoryItem])
async def review_history(asset_id: uuid.UUID, _: Viewer, db: TenantDB) -> list[ReviewHistoryItem]:
    rows = (
        await db.scalars(
            select(ObservationReview)
            .where(ObservationReview.asset_id == asset_id)
            .order_by(ObservationReview.created_at)
        )
    ).all()
    return [ReviewHistoryItem.model_validate(r) for r in rows]
