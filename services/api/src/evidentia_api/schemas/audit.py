from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from evidentia_core.domain.enums import ActorKind

from evidentia_api.schemas.common import ApiModel


class AuditEventOut(ApiModel):
    id: uuid.UUID
    actor_kind: ActorKind
    actor_user_id: uuid.UUID | None
    action: str
    target_type: str
    target_id: uuid.UUID | None
    data: dict[str, Any] | None
    request_id: str | None
    created_at: datetime
