from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from evidentia_api.deps import SettingsDep, TenantDB, Viewer
from evidentia_api.schemas.search import (
    FeedbackRequest,
    SearchRequest,
    SearchResponse,
    SimilarRequest,
    SimilarResult,
)
from evidentia_api.services import search as svc

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    body: SearchRequest, principal: Viewer, db: TenantDB, settings: SettingsDep, request: Request
) -> SearchResponse:
    """Hybrid evidence search. Natural language is parsed into hard filters (site, dates, media type,
    verification) plus text for lexical, semantic and visual retrieval, fused with RRF."""
    state = request.app.state
    return await svc.run_search(
        db,
        principal,
        body,
        settings,
        embedder=state.embedder,
        llms=state.text_llms,
        cloudinary_ready=state.cloudinary is not None,
    )


@router.post("/similar", response_model=list[SimilarResult])
async def similar(
    body: SimilarRequest, _: Viewer, db: TenantDB, settings: SettingsDep, request: Request
) -> list[SimilarResult]:
    return await svc.similar(
        db,
        body.asset_id,
        body.limit,
        body.same_project,
        settings,
        embedder=request.app.state.embedder,
        cloudinary_ready=request.app.state.cloudinary is not None,
    )


@router.post("/{query_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def feedback(
    query_id: uuid.UUID, body: FeedbackRequest, principal: Viewer, db: TenantDB
) -> None:
    """Clicks / 'add to evidence' / dismissals, logged for ranking evaluation and tuning."""
    await svc.record_feedback(db, principal, query_id, body.asset_id, body.action, body.rank)
