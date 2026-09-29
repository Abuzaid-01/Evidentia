from __future__ import annotations

import uuid

from evidentia_core.db.models import AuditEvent
from fastapi import APIRouter, Query
from sqlalchemy import select

from evidentia_api.deps import Manager, TenantDB
from evidentia_api.schemas.audit import AuditEventOut

router = APIRouter(prefix="/v1", tags=["audit"])


@router.get("/audit", response_model=list[AuditEventOut])
async def list_audit(
    _: Manager,
    db: TenantDB,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditEventOut]:
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if target_type:
        query = query.where(AuditEvent.target_type == target_type)
    if target_id:
        query = query.where(AuditEvent.target_id == target_id)
    return [AuditEventOut.model_validate(e) for e in (await db.scalars(query)).all()]
