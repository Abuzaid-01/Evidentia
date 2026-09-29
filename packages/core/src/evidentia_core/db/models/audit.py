"""Append-only audit trail: who changed what, when, in which tenant and why."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk
from evidentia_core.domain.enums import ActorKind


class AuditEvent(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_target", "target_type", "target_id"),)

    actor_kind: Mapped[ActorKind]
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))  # e.g. project.created, asset.uploaded
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID | None]
    data: Mapped[dict[str, Any] | None]
    request_id: Mapped[str | None] = mapped_column(String(64))
