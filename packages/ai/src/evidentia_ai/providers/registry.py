"""Build the ordered provider chain from settings. Unconfigured providers are skipped."""

from __future__ import annotations

from evidentia_cloudinary.analyze import AnalyzeClient
from evidentia_core.config import Settings

from evidentia_ai.providers.base import VisionProvider
from evidentia_ai.providers.cloudinary_vision import CloudinaryVisionProvider
from evidentia_ai.providers.gemini import GeminiVisionProvider
from evidentia_ai.providers.groq import GroqVisionProvider
from evidentia_ai.providers.mock import MockVisionProvider


def build_vision_providers(
    settings: Settings, analyze_client: AnalyzeClient | None
) -> list[VisionProvider]:
    chain: list[VisionProvider] = []
    timeout = settings.ai_request_timeout_seconds
    for name in settings.ai_vision_providers:
        if name == "cloudinary" and analyze_client and settings.cloudinary_analyze_enabled:
            chain.append(CloudinaryVisionProvider(analyze_client))
        elif name == "gemini" and settings.gemini_api_key:
            chain.append(
                GeminiVisionProvider(
                    settings.gemini_api_key.get_secret_value(),
                    settings.gemini_model,
                    timeout=timeout,
                )
            )
        elif name == "groq" and settings.groq_api_key:
            chain.append(
                GroqVisionProvider(
                    settings.groq_api_key.get_secret_value(), settings.groq_model, timeout=timeout
                )
            )
        elif name == "mock":
            chain.append(MockVisionProvider())
    return chain
