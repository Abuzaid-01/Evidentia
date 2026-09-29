"""Worker error taxonomy: decides between retry-with-backoff and fail-permanently."""

from __future__ import annotations

import httpx
from evidentia_ai.providers.base import ProviderRetryableError
from evidentia_cloudinary.errors import CloudinaryRetryableError
from sqlalchemy.exc import OperationalError


class RetryableError(Exception):
    """Transient: Cloudinary 5xx/429, model rate limit, network, DB hiccup."""


class PermanentError(Exception):
    """Will not succeed on retry: unsupported/corrupt media, missing asset, bad configuration."""


TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    RetryableError,
    CloudinaryRetryableError,
    ProviderRetryableError,
    httpx.TransportError,
    OperationalError,
)
