"""Engines and sessions, with tenant context for Postgres row-level security.

Every transaction re-applies the tenant settings (`app.current_org` / `app.rls_bypass`) through an
`after_begin` hook, so the RLS context survives commits within one request or task.

* Request code uses `tenant_session(org_id)`: can only see that organization's rows.
* System code (webhooks, workers) uses `system_session()`: explicitly opts in to bypass RLS and
  must scope its own queries.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from evidentia_core.config import get_settings

_ORG_KEY = "evidentia.org_id"
_BYPASS_KEY = "evidentia.rls_bypass"


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    org_id = session.info.get(_ORG_KEY)
    bypass = session.info.get(_BYPASS_KEY, False)
    connection.execute(
        text(
            "SELECT set_config('app.current_org', :org, true), "
            "set_config('app.rls_bypass', :bypass, true)"
        ),
        {"org": str(org_id) if org_id else "", "bypass": "on" if bypass else "off"},
    )


def _engine_kwargs() -> dict[str, Any]:
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 10}


@lru_cache
def async_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, **_engine_kwargs())


@lru_cache
def sync_engine() -> Engine:
    return create_engine(get_settings().sync_database_url, **_engine_kwargs())


@lru_cache
def _async_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(async_engine(), expire_on_commit=False)


@lru_cache
def _sync_factory() -> sessionmaker[Session]:
    return sessionmaker(sync_engine(), expire_on_commit=False)


def _configure(session: Session, org_id: uuid.UUID | None, bypass: bool) -> None:
    session.info[_ORG_KEY] = org_id
    session.info[_BYPASS_KEY] = bypass


@asynccontextmanager
async def tenant_session(org_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    async with _async_factory()() as session:
        _configure(session.sync_session, org_id, bypass=False)
        yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    async with _async_factory()() as session:
        _configure(session.sync_session, None, bypass=True)
        yield session


@contextmanager
def sync_system_session() -> Iterator[Session]:
    with _sync_factory()() as session:
        _configure(session, None, bypass=True)
        yield session


def set_session_tenant(session: Session | AsyncSession, org_id: uuid.UUID) -> None:
    """Narrow an already-open system session to one tenant (applies from the next transaction)."""
    target = session.sync_session if isinstance(session, AsyncSession) else session
    _configure(target, org_id, bypass=False)
