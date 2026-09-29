from __future__ import annotations

import uuid
from typing import Any

from evidentia_core.db.models import AuditEvent
from evidentia_core.domain.enums import ActorKind
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal


def record(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None,
    principal: Principal | None = None,
    actor_kind: ActorKind | None = None,
    data: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction (committed with the change it describes)."""
    event = AuditEvent(
        organization_id=org_id,
        actor_kind=actor_kind or (ActorKind.USER if principal else ActorKind.SYSTEM),
        actor_user_id=principal.user_id if principal else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        data=data,
        request_id=request_id,
    )
    session.add(event)
    return event
