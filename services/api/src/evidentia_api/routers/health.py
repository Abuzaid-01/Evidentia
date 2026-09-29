from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
from evidentia_core.db.session import system_session
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from evidentia_api.deps import SettingsDep

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict[str, str]:
    return {
        "app": "Evidentia API",
        "status": "ok",
        "docs": "/docs",
        "health": "/healthz",
        "readiness": "/readyz",
    }


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(request: Request, response: Response, settings: SettingsDep) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        async with system_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        client = aioredis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    checks["cloudinary"] = "configured" if request.app.state.cloudinary else "not_configured"
    checks["webhooks"] = "enabled" if settings.webhook_url else "disabled (set PUBLIC_API_BASE_URL)"
    healthy = checks["database"] == "ok" and checks["redis"] == "ok"
    response.status_code = 200 if healthy else 503
    return {"status": "ok" if healthy else "degraded", "checks": checks}
