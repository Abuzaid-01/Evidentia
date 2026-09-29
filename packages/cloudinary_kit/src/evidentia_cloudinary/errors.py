"""Typed errors so callers can decide: retry later, or give up."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

import cloudinary.exceptions as cex

P = ParamSpec("P")
R = TypeVar("R")


class CloudinaryError(Exception):
    """Base class for Cloudinary failures."""


class CloudinaryRetryableError(CloudinaryError):
    """Rate limits, 5xx, network problems: try again with backoff."""


class CloudinaryPermanentError(CloudinaryError):
    """Bad request, auth failure, add-on not enabled: retrying will not help."""


class CloudinaryNotFound(CloudinaryPermanentError):
    """The asset does not exist (or not with that type/resource_type)."""


def translate_sdk_errors(fn: Callable[P, R]) -> Callable[P, R]:
    """Map the Cloudinary SDK's exceptions to our retryable/permanent hierarchy."""

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except cex.NotFound as exc:
            raise CloudinaryNotFound(str(exc)) from exc
        except cex.RateLimited as exc:
            raise CloudinaryRetryableError(f"rate limited: {exc}") from exc
        except (
            cex.BadRequest,
            cex.AuthorizationRequired,
            cex.NotAllowed,
            cex.AlreadyExists,
        ) as exc:
            raise CloudinaryPermanentError(str(exc)) from exc
        except cex.Error as exc:  # GeneralError etc.: usually transient server/network issues
            raise CloudinaryRetryableError(str(exc)) from exc

    return wrapper
