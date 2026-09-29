"""Realtime events: workers publish to Redis, the API streams them to browsers over SSE."""

from __future__ import annotations

import contextlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import redis


def org_channel(org_id: uuid.UUID | str) -> str:
    return f"evidentia:org:{org_id}:events"


def build_event(event_type: str, **data: Any) -> dict[str, Any]:
    return {
        "type": event_type,
        "at": datetime.now(UTC).isoformat(),
        **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in data.items()},
    }


class EventPublisher:
    """Best-effort publisher. Realtime updates are a UX nicety; failures never break processing."""

    def __init__(self, redis_url: str) -> None:
        self._client = redis.Redis.from_url(redis_url)

    def publish(self, org_id: uuid.UUID | str, event: dict[str, Any]) -> None:
        with contextlib.suppress(redis.RedisError):
            self._client.publish(org_channel(org_id), json.dumps(event, default=str))
