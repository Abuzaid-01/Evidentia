"""Client for Cloudinary's Analyze API (Public Beta).

POST https://api.cloudinary.com/v2/analysis/<cloud>/analyze/<model>
Used for: captioning, image_quality, ai_vision_tagging (our taxonomy questions, max 10 per call)
and ai_vision_general (open prompts, with a JSON schema fenced in the prompt for structured output).

Because the API is Beta, callers depend on this narrow interface, never on raw response shapes,
and every call has a non-Cloudinary fallback in the AI layer.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from evidentia_cloudinary.config import CloudinaryCredentials
from evidentia_cloudinary.errors import CloudinaryPermanentError, CloudinaryRetryableError

BASE_URL = "https://api.cloudinary.com/v2/analysis/{cloud}/analyze/{model}"
MAX_TAG_DEFINITIONS = 10
MAX_PROMPTS = 10


@dataclass(frozen=True)
class AnalyzeResult:
    model: str
    analysis: dict[str, Any]
    model_version: str | None
    request_id: str | None
    quota: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


def source_uri(uri: str) -> dict[str, Any]:
    return {"uri": uri}


def source_asset(asset_id: str) -> dict[str, Any]:
    return {"asset_id": asset_id}


class AnalyzeClient:
    def __init__(
        self,
        creds: CloudinaryCredentials,
        *,
        timeout: float = 60.0,
        http: httpx.Client | None = None,
    ) -> None:
        self._creds = creds
        self._http = http or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def run(self, model: str, source: dict[str, Any], **body: Any) -> AnalyzeResult:
        url = BASE_URL.format(cloud=self._creds.cloud_name, model=model)
        started = time.perf_counter()
        try:
            response = self._http.post(
                url,
                json={"source": source, **body},
                auth=(self._creds.api_key, self._creds.api_secret),
            )
        except httpx.TransportError as exc:
            raise CloudinaryRetryableError(f"analyze/{model}: network error: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code == 429 or response.status_code >= 500:
            raise CloudinaryRetryableError(f"analyze/{model}: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise CloudinaryPermanentError(
                f"analyze/{model}: HTTP {response.status_code}: {_error_message(response)}"
            )

        payload = response.json()
        data = payload.get("data") or {}
        analysis = data.get("analysis") or {}
        return AnalyzeResult(
            model=model,
            analysis=analysis,
            model_version=_str_or_none(analysis.get("model_version")),
            request_id=payload.get("request_id"),
            quota=list((payload.get("limits") or {}).get("addons_quota") or []),
            latency_ms=latency_ms,
            raw=payload,
        )

    # --- typed helpers ------------------------------------------------------------
    def captioning(self, source: dict[str, Any]) -> AnalyzeResult:
        return self.run("captioning", source)

    def image_quality(self, source: dict[str, Any]) -> AnalyzeResult:
        return self.run("image_quality", source)

    def ai_vision_tagging(
        self, source: dict[str, Any], tag_definitions: list[dict[str, str]]
    ) -> AnalyzeResult:
        if not 0 < len(tag_definitions) <= MAX_TAG_DEFINITIONS:
            raise ValueError(f"ai_vision_tagging accepts 1..{MAX_TAG_DEFINITIONS} tag definitions")
        return self.run("ai_vision_tagging", source, tag_definitions=tag_definitions)

    def ai_vision_general(self, source: dict[str, Any], prompts: list[str]) -> AnalyzeResult:
        if not 0 < len(prompts) <= MAX_PROMPTS:
            raise ValueError(f"ai_vision_general accepts 1..{MAX_PROMPTS} prompts")
        return self.run("ai_vision_general", source, prompts=prompts)


def structured_prompt(instruction: str, json_schema: dict[str, Any]) -> str:
    """Cloudinary's documented structured-output convention: a ```json fenced schema in the prompt."""
    return f"{instruction}\n```json\n{json.dumps(json_schema, separators=(',', ':'))}\n```"


def caption_text(result: AnalyzeResult) -> str | None:
    value = (result.analysis.get("data") or {}).get("caption")
    return str(value) if value else None


_TAG_UNSAFE = re.compile(r"[^a-z0-9-]+")


def cloudinary_tag_name(key: str) -> str:
    """AI Vision tag names may only contain lower-case letters, digits and hyphens
    (`pipe_installation` -> `pipe-installation`); anything else is rejected with HTTP 400."""
    return _TAG_UNSAFE.sub("-", key.lower()).strip("-")


def tagged_names(result: AnalyzeResult) -> list[str]:
    return [str(t["name"]) for t in result.analysis.get("tags") or [] if t.get("name")]


def general_responses(result: AnalyzeResult) -> list[str]:
    return [str(r.get("value", "")) for r in result.analysis.get("responses") or []]


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message", error))
        details = error.get("details")
        # "invalid request" alone is useless; Cloudinary puts the actual reason in details.message
        if isinstance(details, dict) and details.get("message"):
            message = f"{message}: {details['message']}"
        return message[:300]
    return str(body)[:300]
