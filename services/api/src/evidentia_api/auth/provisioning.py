"""Just-in-time provisioning: map a verified token identity to our org/user/membership rows.

Idempotent and race-safe (INSERT ... ON CONFLICT). Results are cached briefly so we don't write to
the database on every request.
"""

from __future__ import annotations

import time
import uuid

from evidentia_core.db.models import Membership, Organization, User
from evidentia_core.db.session import system_session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Identity, Principal

_CACHE_TTL_SECONDS = 120
_cache: dict[tuple[str, str, str], tuple[float, Principal]] = {}


async def _upsert_org(session: AsyncSession, identity: Identity) -> uuid.UUID:
    await session.execute(
        insert(Organization)
        .values(
            external_id=identity.external_org_id,
            name=identity.org_name or identity.org_slug or identity.external_org_id,
            slug=identity.org_slug,
        )
        .on_conflict_do_nothing(index_elements=[Organization.external_id])
    )
    org_id = await session.scalar(
        select(Organization.id).where(Organization.external_id == identity.external_org_id)
    )
    assert org_id is not None
    return org_id


async def _upsert_user(session: AsyncSession, identity: Identity) -> uuid.UUID:
    stmt = insert(User).values(
        external_id=identity.external_user_id,
        email=identity.email,
        display_name=identity.display_name,
    )
    updates = {}
    if identity.email:
        updates["email"] = stmt.excluded.email
    if identity.display_name:
        updates["display_name"] = stmt.excluded.display_name
    stmt = (
        stmt.on_conflict_do_update(index_elements=[User.external_id], set_=updates)
        if updates
        else stmt.on_conflict_do_nothing(index_elements=[User.external_id])
    )
    await session.execute(stmt)
    user_id = await session.scalar(
        select(User.id).where(User.external_id == identity.external_user_id)
    )
    assert user_id is not None
    return user_id


async def _upsert_membership(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, identity: Identity
) -> Membership:
    await session.execute(
        insert(Membership)
        .values(organization_id=org_id, user_id=user_id, role=identity.token_role)
        .on_conflict_do_nothing(index_elements=[Membership.organization_id, Membership.user_id])
    )
    membership = await session.scalar(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.user_id == user_id
        )
    )
    assert membership is not None
    # The identity provider stays the source of truth for roles unless an admin pinned one.
    if not membership.role_locked and membership.role != identity.token_role:
        membership.role = identity.token_role
    return membership


async def resolve_principal(identity: Identity) -> Principal:
    key = (identity.external_user_id, identity.external_org_id, identity.token_role.value)
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    async with system_session() as session:
        org_id = await _upsert_org(session, identity)
        user_id = await _upsert_user(session, identity)
        membership = await _upsert_membership(session, org_id, user_id, identity)
        await session.commit()
        principal = Principal(
            user_id=user_id,
            org_id=org_id,
            role=membership.role,
            external_user_id=identity.external_user_id,
            external_org_id=identity.external_org_id,
            display_name=identity.display_name,
        )

    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, principal)
    return principal


def clear_cache() -> None:
    _cache.clear()
