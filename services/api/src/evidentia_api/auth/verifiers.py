"""Token verification: Clerk (production) and a local-only dev scheme."""

from __future__ import annotations

import re
from typing import Any, Protocol

import anyio
import jwt
from evidentia_core.config import Settings
from evidentia_core.domain.enums import Role

from evidentia_api.auth.principal import Identity
from evidentia_api.errors import Forbidden, Unauthorized

# Clerk organization roles -> Evidentia roles. Custom Clerk roles (org:reviewer, org:manager,
# org:viewer) map directly; unknown roles get the least privileged working role.
_CLERK_ROLES = {
    "org:admin": Role.ADMIN,
    "admin": Role.ADMIN,
    "org:manager": Role.MANAGER,
    "org:reviewer": Role.REVIEWER,
    "org:member": Role.CONTRIBUTOR,
    "basic_member": Role.CONTRIBUTOR,
    "org:contributor": Role.CONTRIBUTOR,
    "org:viewer": Role.VIEWER,
}


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> Identity: ...


class ClerkVerifier:
    def __init__(self, settings: Settings) -> None:
        jwks_url = settings.resolved_clerk_jwks_url
        if not (settings.clerk_issuer and jwks_url):
            raise RuntimeError("Clerk auth needs CLERK_ISSUER")
        self._issuer = settings.clerk_issuer.rstrip("/")
        self._parties = set(settings.clerk_authorized_parties)
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)

    async def verify(self, token: str) -> Identity:
        try:
            # PyJWKClient uses blocking I/O on cache misses: keep it off the event loop.
            key = await anyio.to_thread.run_sync(self._jwks.get_signing_key_from_jwt, token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub"]},
                leeway=5,
            )
        except jwt.PyJWTError as exc:
            raise Unauthorized(f"Invalid session token: {exc}") from exc

        azp = claims.get("azp")
        if azp and self._parties and azp not in self._parties:
            raise Unauthorized("Token was issued for a different origin")

        org = claims.get("o") if isinstance(claims.get("o"), dict) else {}
        org_id = org.get("id") or claims.get("org_id")
        if not org_id:
            raise Forbidden("Select or create an organization to continue", code="no_organization")
        role_claim = org.get("rol") or claims.get("org_role") or ""
        role_key = (
            role_claim
            if role_claim.startswith("org:") or role_claim in _CLERK_ROLES
            else f"org:{role_claim}"
        )
        return Identity(
            external_user_id=str(claims["sub"]),
            external_org_id=str(org_id),
            token_role=_CLERK_ROLES.get(role_key, Role.CONTRIBUTOR),
            org_slug=org.get("slg") or claims.get("org_slug"),
            org_name=org.get("slg") or claims.get("org_slug"),
            email=claims.get("email"),
            display_name=claims.get("name"),
        )


_DEV_TOKEN = re.compile(
    r"^dev\.(?P<user>[a-z0-9_-]{1,40})\.(?P<org>[a-z0-9_-]{1,40})\.(?P<role>[a-z]+)$"
)


class DevVerifier:
    """LOCAL ONLY. Token: `dev.<user>.<org>.<role>`, e.g. `dev.asha.jalseva.manager`.

    Settings refuse AUTH_MODE=dev outside local/test environments.
    """

    async def verify(self, token: str) -> Identity:
        match = _DEV_TOKEN.match(token)
        if not match:
            raise Unauthorized("Dev token must look like dev.<user>.<org>.<role>")
        try:
            role = Role(match["role"])
        except ValueError as exc:
            raise Unauthorized(f"Unknown role '{match['role']}'") from exc
        user, org = match["user"], match["org"]
        return Identity(
            external_user_id=f"dev_user_{user}",
            external_org_id=f"dev_org_{org}",
            token_role=role,
            org_name=org.replace("-", " ").replace("_", " ").title(),
            org_slug=org,
            email=f"{user}@{org}.dev.local",
            display_name=user.replace("-", " ").replace("_", " ").title(),
        )


def build_verifier(settings: Settings) -> TokenVerifier:
    if settings.auth_mode == "clerk":
        return ClerkVerifier(settings)
    return DevVerifier()
