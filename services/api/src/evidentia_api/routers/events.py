"""Server-sent events: live pipeline progress for the caller's organization."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis
from evidentia_core.events import org_channel
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from evidentia_api.deps import SettingsDep, Viewer

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.get("/stream")
async def stream(request: Request, principal: Viewer, settings: SettingsDep) -> EventSourceResponse:
    async def events() -> AsyncIterator[dict[str, Any]]:
        client = aioredis.from_url(settings.redis_url)
        pubsub = client.pubsub()
        await pubsub.subscribe(org_channel(principal.org_id))
        try:
            yield {"event": "ready", "data": json.dumps({"org_id": str(principal.org_id)})}
            while not await request.is_disconnected():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                data = message["data"]
                payload = data.decode() if isinstance(data, bytes) else str(data)
                event_type = json.loads(payload).get("type", "message")
                yield {"event": event_type, "data": payload}
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
            await client.aclose()

    return EventSourceResponse(events(), ping=15)
