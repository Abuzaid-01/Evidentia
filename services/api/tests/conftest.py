"""Shared fixtures for API integration tests (real Postgres + Redis; Cloudinary never contacted)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest


@pytest.fixture
def org() -> str:
    return f"org{uuid.uuid4().hex[:10]}"


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[str, ...]]]:
    calls: list[tuple[str, tuple[str, ...]]] = []
    import evidentia_core.tasks as tasks

    monkeypatch.setattr(tasks, "enqueue", lambda name, *args: calls.append((name, args)) or "id")
    return calls


@pytest.fixture
async def client(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    from evidentia_api.auth.provisioning import clear_cache
    from evidentia_api.main import create_app
    from evidentia_core.db.session import async_engine

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    clear_cache()
    await async_engine().dispose()
