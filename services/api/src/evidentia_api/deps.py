"""FastAPI dependencies: settings, the authenticated principal, and tenant-scoped DB sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from evidentia_cloudinary import CloudinaryCredentials
from evidentia_core.config import Settings, get_settings
from evidentia_core.db.session import tenant_session
from evidentia_core.domain.enums import Role
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.auth.provisioning import resolve_principal
from evidentia_api.errors import ServiceUnavailable, Unauthorized

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Missing bearer token")
    return token.strip()


async def get_principal(request: Request) -> Principal:
    verifier = request.app.state.verifier
    identity = await verifier.verify(_bearer(request))
    principal = await resolve_principal(identity)
    request.state.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def get_tenant_db(principal: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    async with tenant_session(principal.org_id) as session:
        yield session


TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]


def require_role(role: Role) -> Callable[[Principal], Coroutine[Any, Any, Principal]]:
    async def _check(principal: CurrentPrincipal) -> Principal:
        principal.require(role)
        return principal

    return _check


Viewer = Annotated[Principal, Depends(require_role(Role.VIEWER))]
Contributor = Annotated[Principal, Depends(require_role(Role.CONTRIBUTOR))]
Reviewer = Annotated[Principal, Depends(require_role(Role.REVIEWER))]
Manager = Annotated[Principal, Depends(require_role(Role.MANAGER))]
Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]


def get_cloudinary(request: Request) -> CloudinaryCredentials:
    creds: CloudinaryCredentials | None = request.app.state.cloudinary
    if creds is None:
        raise ServiceUnavailable("Cloudinary is not configured (set CLOUDINARY_URL)")
    return creds


CloudinaryDep = Annotated[CloudinaryCredentials, Depends(get_cloudinary)]


def request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


RequestId = Annotated[str | None, Depends(request_id)]
