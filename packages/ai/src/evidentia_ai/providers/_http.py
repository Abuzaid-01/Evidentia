"""Shared HTTP error mapping for provider adapters."""

from __future__ import annotations

import time
from typing import Any

import httpx

from evidentia_ai.providers.base import ProviderPermanentError, ProviderRetryableError


def post_json(
    client: httpx.Client, url: str, *, provider: str, **kwargs: Any
) -> tuple[dict[str, Any], int]:
    started = time.perf_counter()
    try:
        response = client.post(url, **kwargs)
    except httpx.TimeoutException as exc:
        raise ProviderRetryableError(f"{provider}: timeout") from exc
    except httpx.TransportError as exc:
        raise ProviderRetryableError(f"{provider}: network error: {exc}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)

    if response.status_code == 429 or response.status_code >= 500:
        raise ProviderRetryableError(f"{provider}: HTTP {response.status_code}")
    if response.status_code >= 400:
        raise ProviderPermanentError(
            f"{provider}: HTTP {response.status_code}: {response.text[:300]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderRetryableError(f"{provider}: non-JSON response") from exc
    return payload, latency_ms
