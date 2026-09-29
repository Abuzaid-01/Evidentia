from __future__ import annotations

import uuid

from evidentia_core.db.models import Claim, EvidenceLink, Metric
from evidentia_core.domain.enums import ClaimStatus
from fastapi import APIRouter, Request, status
from sqlalchemy import select

from evidentia_api.deps import (
    Contributor,
    Manager,
    RequestId,
    Reviewer,
    SettingsDep,
    TenantDB,
    Viewer,
)
from evidentia_api.schemas.claims import (
    ClaimCreate,
    ClaimDetail,
    ClaimOut,
    ClaimUpdate,
    DecisionBody,
    EventCreate,
    EventOut,
    EventSuggestion,
    EvidenceGraph,
    EvidenceLinkCreate,
    EvidenceLinkOut,
    MetricCreate,
    MetricOut,
)
from evidentia_api.services import claims as svc

router = APIRouter(prefix="/v1", tags=["claims"])


def _ready(request: Request) -> bool:
    return request.app.state.cloudinary is not None


# --- metrics ----------------------------------------------------------------------------------


@router.get("/projects/{project_id}/metrics", response_model=list[MetricOut])
async def list_metrics(project_id: uuid.UUID, _: Viewer, db: TenantDB) -> list[MetricOut]:
    await svc.project_or_404(db, project_id)
    rows = (
        await db.scalars(
            select(Metric).where(Metric.project_id == project_id).order_by(Metric.created_at)
        )
    ).all()
    return [MetricOut.model_validate(m) for m in rows]


@router.post(
    "/projects/{project_id}/metrics", response_model=MetricOut, status_code=status.HTTP_201_CREATED
)
async def create_metric(
    project_id: uuid.UUID, body: MetricCreate, principal: Manager, db: TenantDB, rid: RequestId
) -> MetricOut:
    return MetricOut.model_validate(await svc.create_metric(db, principal, project_id, body, rid))


# --- claims -------------------------------------------------------------------------------------


@router.get("/projects/{project_id}/claims", response_model=list[ClaimOut])
async def list_claims(
    project_id: uuid.UUID, _: Viewer, db: TenantDB, status_filter: ClaimStatus | None = None
) -> list[ClaimOut]:
    await svc.project_or_404(db, project_id)
    query = select(Claim).where(Claim.project_id == project_id).order_by(Claim.created_at.desc())
    if status_filter:
        query = query.where(Claim.status == status_filter)
    return [ClaimOut.model_validate(c) for c in (await db.scalars(query)).all()]


@router.post(
    "/projects/{project_id}/claims", response_model=ClaimOut, status_code=status.HTTP_201_CREATED
)
async def create_claim(
    project_id: uuid.UUID, body: ClaimCreate, principal: Contributor, db: TenantDB, rid: RequestId
) -> ClaimOut:
    return ClaimOut.model_validate(await svc.create_claim(db, principal, project_id, body, rid))


@router.get("/claims/{claim_id}", response_model=ClaimDetail)
async def get_claim(
    claim_id: uuid.UUID, _: Viewer, db: TenantDB, settings: SettingsDep, request: Request
) -> ClaimDetail:
    claim = await svc.get_claim(db, claim_id)
    return await svc.claim_detail(db, claim, settings, cloudinary_ready=_ready(request))


@router.patch("/claims/{claim_id}", response_model=ClaimOut)
async def update_claim(
    claim_id: uuid.UUID, body: ClaimUpdate, principal: Contributor, db: TenantDB, rid: RequestId
) -> ClaimOut:
    return ClaimOut.model_validate(await svc.update_claim(db, principal, claim_id, body, rid))


@router.post(
    "/claims/{claim_id}/evidence",
    response_model=EvidenceLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_evidence(
    claim_id: uuid.UUID,
    body: EvidenceLinkCreate,
    principal: Contributor,
    db: TenantDB,
    rid: RequestId,
) -> EvidenceLinkOut:
    link: EvidenceLink = await svc.add_evidence(db, principal, claim_id, body, rid)
    return EvidenceLinkOut.model_validate(link)


@router.delete("/claims/{claim_id}/evidence/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_evidence(
    claim_id: uuid.UUID, link_id: uuid.UUID, principal: Contributor, db: TenantDB, rid: RequestId
) -> None:
    await svc.remove_evidence(db, principal, claim_id, link_id, rid)


@router.put("/claims/{claim_id}/metrics/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
async def link_metric(
    claim_id: uuid.UUID, metric_id: uuid.UUID, principal: Contributor, db: TenantDB, rid: RequestId
) -> None:
    await svc.set_metric_link(db, principal, claim_id, metric_id, linked=True, rid=rid)


@router.delete("/claims/{claim_id}/metrics/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_metric(
    claim_id: uuid.UUID, metric_id: uuid.UUID, principal: Contributor, db: TenantDB, rid: RequestId
) -> None:
    await svc.set_metric_link(db, principal, claim_id, metric_id, linked=False, rid=rid)


@router.post("/claims/{claim_id}/validate", response_model=ClaimOut)
async def validate_claim(
    claim_id: uuid.UUID, principal: Contributor, db: TenantDB, request: Request, rid: RequestId
) -> ClaimOut:
    """Deterministic evidence rules + LLM check against the linked evidence only."""
    return ClaimOut.model_validate(
        await svc.validate(db, principal, claim_id, request.app.state.text_llms, rid)
    )


@router.post("/claims/{claim_id}/submit", response_model=ClaimOut)
async def submit(
    claim_id: uuid.UUID,
    principal: Contributor,
    db: TenantDB,
    rid: RequestId,
    body: DecisionBody | None = None,
) -> ClaimOut:
    return ClaimOut.model_validate(
        await svc.transition(
            db, principal, claim_id, ClaimStatus.IN_REVIEW, body or DecisionBody(), rid
        )
    )


@router.post("/claims/{claim_id}/approve", response_model=ClaimOut)
async def approve(
    claim_id: uuid.UUID, body: DecisionBody, principal: Reviewer, db: TenantDB, rid: RequestId
) -> ClaimOut:
    return ClaimOut.model_validate(
        await svc.transition(db, principal, claim_id, ClaimStatus.APPROVED, body, rid)
    )


@router.post("/claims/{claim_id}/reject", response_model=ClaimOut)
async def reject(
    claim_id: uuid.UUID, body: DecisionBody, principal: Reviewer, db: TenantDB, rid: RequestId
) -> ClaimOut:
    return ClaimOut.model_validate(
        await svc.transition(db, principal, claim_id, ClaimStatus.REJECTED, body, rid)
    )


@router.post("/claims/{claim_id}/retract", response_model=ClaimOut)
async def retract(
    claim_id: uuid.UUID, body: DecisionBody, principal: Manager, db: TenantDB, rid: RequestId
) -> ClaimOut:
    return ClaimOut.model_validate(
        await svc.transition(db, principal, claim_id, ClaimStatus.RETRACTED, body, rid)
    )


@router.get("/claims/{claim_id}/graph", response_model=EvidenceGraph)
async def graph(claim_id: uuid.UUID, _: Viewer, db: TenantDB) -> EvidenceGraph:
    """claim <- evidence link <- observation <- asset (Cloudinary public_id) ; claim <- metric."""
    return await svc.claim_graph(db, await svc.get_claim(db, claim_id))


# --- activity events ----------------------------------------------------------------------------------


@router.get("/projects/{project_id}/events", response_model=list[EventOut])
async def list_events(project_id: uuid.UUID, _: Viewer, db: TenantDB) -> list[EventOut]:
    await svc.project_or_404(db, project_id)
    return await svc.list_events(db, project_id)


@router.get("/projects/{project_id}/events/suggestions", response_model=list[EventSuggestion])
async def suggest_events(project_id: uuid.UUID, _: Viewer, db: TenantDB) -> list[EventSuggestion]:
    return await svc.suggest_events(db, project_id)


@router.post(
    "/projects/{project_id}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED
)
async def create_event(
    project_id: uuid.UUID, body: EventCreate, principal: Reviewer, db: TenantDB, rid: RequestId
) -> EventOut:
    return await svc.create_event(db, principal, project_id, body, rid)
