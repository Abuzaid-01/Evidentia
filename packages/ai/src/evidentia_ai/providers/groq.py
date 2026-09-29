"""Groq (OpenAI-compatible chat completions) with a vision-capable model and JSON mode."""

from __future__ import annotations

import httpx

from evidentia_ai.parsing import ExtractionInvalid, parse_extraction
from evidentia_ai.prompts import AnalysisContext
from evidentia_ai.providers._http import post_json
from evidentia_ai.providers.base import ImageInput, ProviderPermanentError, ProviderResult

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
MAX_BASE64_BYTES = 4 * 1024 * 1024  # Groq's documented limit for base64 images


class GroqVisionProvider:
    name = "groq"

    def __init__(self, api_key: str, model: str, *, timeout: float = 60.0) -> None:
        self.model = model
        self._api_key = api_key
        self._http = httpx.Client(timeout=timeout)

    def extract(self, image: ImageInput, ctx: AnalysisContext, prompt: str) -> ProviderResult:
        encoded = image.base64()
        if len(encoded) > MAX_BASE64_BYTES:
            raise ProviderPermanentError("groq: image too large for base64 input")
        body = {
            "model": self.model,
            "temperature": 0.1,
            "max_completion_tokens": 2048,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{image.mime_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
        }
        payload, latency_ms = post_json(
            self._http,
            ENDPOINT,
            provider=self.name,
            json=body,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        choices = payload.get("choices") or []
        text = str(((choices[0] if choices else {}).get("message") or {}).get("content") or "")
        if not text:
            raise ProviderPermanentError("groq: empty response")
        try:
            extraction = parse_extraction(text, {a.key for a in ctx.activities})
        except ExtractionInvalid as exc:
            raise ProviderPermanentError(f"groq: {exc}") from exc
        return ProviderResult(
            extraction=extraction,
            provider=self.name,
            model=str(payload.get("model") or self.model),
            model_version=payload.get("system_fingerprint"),
            raw={"text": text, "usage": payload.get("usage")},
            latency_ms=latency_ms,
            usage=dict(payload.get("usage") or {}),
        )
