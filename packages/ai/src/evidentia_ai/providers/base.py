from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Protocol

from evidentia_ai.prompts import AnalysisContext
from evidentia_ai.schemas import VisionExtraction


class ProviderRetryableError(Exception):
    """Rate limit / timeout / 5xx: try again later (or try the next provider)."""


class ProviderPermanentError(Exception):
    """Not configured, invalid key, content rejected, invalid output after retries."""


@dataclass(frozen=True)
class ImageInput:
    data: bytes
    mime_type: str
    # A signed URL of the same rendition. Only Cloudinary's own API uses it (the image never leaves
    # Cloudinary); third-party providers receive the bytes instead of a reusable URL.
    cloudinary_url: str | None = None

    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


@dataclass(frozen=True)
class ProviderResult:
    extraction: VisionExtraction
    provider: str
    model: str
    model_version: str | None
    raw: dict[str, Any]
    latency_ms: int
    usage: dict[str, Any] = field(default_factory=dict)


class VisionProvider(Protocol):
    name: str
    model: str

    def extract(self, image: ImageInput, ctx: AnalysisContext, prompt: str) -> ProviderResult: ...
