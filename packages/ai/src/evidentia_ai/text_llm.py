"""Text-only JSON LLM providers (Gemini, Groq) for query planning and claim validation.

Same rules as vision: JSON mode, Pydantic validation by the caller, provider chain with fallback,
retryable vs permanent errors kept distinct.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from evidentia_core.config import Settings

from evidentia_ai.parsing import ExtractionInvalid, extract_json_object
from evidentia_ai.providers._http import post_json
from evidentia_ai.providers.base import ProviderPermanentError, ProviderRetryableError


@dataclass(frozen=True)
class JsonAnswer:
    data: dict[str, Any]
    provider: str
    model: str
    latency_ms: int


class TextLLM(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str) -> JsonAnswer: ...


def _parse(text: str, provider: str) -> dict[str, Any]:
    try:
        return extract_json_object(text)
    except ExtractionInvalid as exc:
        raise ProviderPermanentError(f"{provider}: {exc}") from exc


class GeminiText:
    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.model, self._key = model, api_key
        self._http = httpx.Client(timeout=timeout)

    def complete_json(self, system: str, user: str) -> JsonAnswer:
        payload, ms = post_json(
            self._http,
            self.URL.format(model=self.model),
            provider=self.name,
            headers={"x-goog-api-key": self._key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
            },
        )
        parts = ((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(str(p.get("text", "")) for p in parts)
        if not text:
            raise ProviderPermanentError("gemini: empty response")
        return JsonAnswer(_parse(text, self.name), self.name, self.model, ms)


class GroqText:
    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.model, self._key = model, api_key
        self._http = httpx.Client(timeout=timeout)

    def complete_json(self, system: str, user: str) -> JsonAnswer:
        payload, ms = post_json(
            self._http,
            self.URL,
            provider=self.name,
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        choices = payload.get("choices") or [{}]
        text = str((choices[0].get("message") or {}).get("content") or "")
        if not text:
            raise ProviderPermanentError("groq: empty response")
        return JsonAnswer(_parse(text, self.name), self.name, self.model, ms)


class MockText:
    """Echoes a canned answer (tests). Only used when LLM_TEXT_PROVIDERS includes "mock"."""

    name = "mock"
    model = "mock-text-1"

    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.answer = answer or {}

    def complete_json(self, system: str, user: str) -> JsonAnswer:
        return JsonAnswer(json.loads(json.dumps(self.answer)), self.name, self.model, 0)


def build_text_llms(settings: Settings) -> list[TextLLM]:
    chain: list[TextLLM] = []
    timeout = min(settings.ai_request_timeout_seconds, 30.0)
    for name in settings.llm_text_providers:
        if name == "gemini" and settings.gemini_api_key:
            chain.append(
                GeminiText(
                    settings.gemini_api_key.get_secret_value(), settings.gemini_text_model, timeout
                )
            )
        elif name == "groq" and settings.groq_api_key:
            chain.append(
                GroqText(
                    settings.groq_api_key.get_secret_value(), settings.groq_text_model, timeout
                )
            )
        elif name == "mock":
            chain.append(MockText())
    return chain


def first_answer(
    chain: list[TextLLM], system: str, user: str
) -> tuple[JsonAnswer | None, list[str]]:
    """Try providers in order. Returns (answer or None, errors). Never raises."""
    errors: list[str] = []
    for llm in chain:
        try:
            return llm.complete_json(system, user), errors
        except (ProviderRetryableError, ProviderPermanentError) as exc:
            errors.append(f"{llm.name}: {exc}")
    return None, errors
