"""Google Gemini (REST, generateContent) with JSON output mode."""

from __future__ import annotations

from typing import Any

import httpx

from evidentia_ai.parsing import ExtractionInvalid, parse_extraction
from evidentia_ai.prompts import AnalysisContext
from evidentia_ai.providers._http import post_json
from evidentia_ai.providers.base import ImageInput, ProviderPermanentError, ProviderResult

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiVisionProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, *, timeout: float = 60.0) -> None:
        self.model = model
        self._api_key = api_key
        self._http = httpx.Client(timeout=timeout)

    def extract(self, image: ImageInput, ctx: AnalysisContext, prompt: str) -> ProviderResult:
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inline_data": {"mime_type": image.mime_type, "data": image.base64()}},
                        {"text": prompt},
                    ],
                }
            ],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
        }
        payload, latency_ms = post_json(
            self._http,
            ENDPOINT.format(model=self.model),
            provider=self.name,
            json=body,
            headers={"x-goog-api-key": self._api_key},
        )
        text = _candidate_text(payload)
        try:
            extraction = parse_extraction(text, {a.key for a in ctx.activities})
        except ExtractionInvalid as exc:
            raise ProviderPermanentError(f"gemini: {exc}") from exc
        return ProviderResult(
            extraction=extraction,
            provider=self.name,
            model=self.model,
            model_version=payload.get("modelVersion"),
            raw={"text": text, "usageMetadata": payload.get("usageMetadata")},
            latency_ms=latency_ms,
            usage=dict(payload.get("usageMetadata") or {}),
        )


def _candidate_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        feedback = payload.get("promptFeedback", {})
        raise ProviderPermanentError(f"gemini: no candidates (feedback: {feedback})")
    candidate = candidates[0]
    if candidate.get("finishReason") in {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"}:
        raise ProviderPermanentError(f"gemini: blocked ({candidate.get('finishReason')})")
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(str(p.get("text", "")) for p in parts)
    if not text:
        raise ProviderPermanentError("gemini: empty response")
    return text
