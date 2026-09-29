from __future__ import annotations

import uuid

from evidentia_core.domain.enums import Role

from evidentia_api.schemas.common import ApiModel


class UserOut(ApiModel):
    id: uuid.UUID
    display_name: str | None
    email: str | None


class OrganizationOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str | None


class MeOut(ApiModel):
    user: UserOut
    organization: OrganizationOut
    role: Role
    auth_mode: str
    cloudinary_cloud_name: str | None
    features: dict[str, bool]
