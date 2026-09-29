from __future__ import annotations

import uuid
from dataclasses import dataclass

from evidentia_core.domain.enums import Role

from evidentia_api.errors import Forbidden


@dataclass(frozen=True)
class Identity:
    """What a verified token says about the caller (before mapping to our database)."""

    external_user_id: str
    external_org_id: str
    token_role: Role
    org_name: str | None = None
    org_slug: str | None = None
    email: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, resolved to our own ids. Every request is scoped to one org."""

    user_id: uuid.UUID
    org_id: uuid.UUID
    role: Role
    external_user_id: str
    external_org_id: str
    display_name: str | None = None

    def require(self, role: Role) -> None:
        if not self.role.at_least(role):
            raise Forbidden(
                f"This action needs the '{role.value}' role (you are '{self.role.value}')"
            )
