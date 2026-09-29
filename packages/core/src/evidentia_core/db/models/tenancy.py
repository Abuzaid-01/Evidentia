"""Identity layer: organizations (tenants), users and memberships. Not RLS-protected; always
queried by explicit identifiers resolved from a verified token."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, Timestamps, UUIDPk
from evidentia_core.domain.enums import Role


class Organization(UUIDPk, Timestamps, Base):
    __tablename__ = "organizations"

    external_id: Mapped[str] = mapped_column(String(128), unique=True)  # Clerk org id
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str | None] = mapped_column(String(120))


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    external_id: Mapped[str] = mapped_column(String(128), unique=True)  # Clerk user id
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200))


class Membership(UUIDPk, Timestamps, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[Role]
    # True when an admin set the role in Evidentia; then token roles don't overwrite it.
    role_locked: Mapped[bool] = mapped_column(default=False)
