"""Cloudinary AI Video Analysis (Beta).

POST/GET https://api.cloudinary.com/v2/video/<cloud>/ai_video_analysis
The call is asynchronous: start returns a job id, polling returns a raw transcript file of
timestamped visual descriptions. Callers treat every failure as "use the keyframe fallback".
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from evidentia_cloudinary.config import CloudinaryCredentials
from evidentia_cloudinary.errors import CloudinaryPermanentError, CloudinaryRetryableError

BASE = "https://api.cloudinary.com/v2/video/{cloud}/ai_video_analysis"


@dataclass(frozen=True)
class VideoJob:
    job_id: str
    status: str  # pending | completed | failed | <anything else, treated as pending>
    url: str | None = None
    error: str | None = None


class VideoAnalysisClient:
    def __init__(
        self,
        creds: CloudinaryCredentials,
        *,
        timeout: float = 60.0,
        http: httpx.Client | None = None,
    ) -> None:
        self._creds = creds
        self._http = http or httpx.Client(timeout=timeout)
        self._owns_http = http is None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def start(self, video_asset_id: str, prompt: str | None = None) -> str:
        body: dict[str, Any] = {"video_asset_id": video_asset_id}
        if prompt:
            body["visual_transcription_prompt"] = prompt
        payload = self._request("POST", "", json=body, ok=(200, 201))
        data = payload.get("data") or {}
        job_id = data.get("job_id")
        if not job_id:
            raise CloudinaryPermanentError("ai_video_analysis: response had no job_id")
        return str(job_id)

    def status(self, job_id: str) -> VideoJob:
        payload = self._request("GET", f"/{job_id}", ok=(200,))
        data = payload.get("data") or {}
        transcript = data.get("visual_transcription") or {}
        return VideoJob(
            job_id=str(data.get("job_id") or job_id),
            status=str(data.get("status") or "pending"),
            url=transcript.get("url"),
            error=_error_text(payload),
        )

    def fetch(self, url: str) -> list[dict[str, Any]]:
        """Download the visual-transcription JSON (a list of timestamped descriptions)."""
        try:
            response = self._http.get(url)
        except httpx.TransportError as exc:
            raise CloudinaryRetryableError(f"ai_video_analysis file: {exc}") from exc
        if response.status_code == 401:
            # Some accounts serve the raw file privately. Retry with the API credentials.
            try:
                response = self._http.get(url, auth=(self._creds.api_key, self._creds.api_secret))
            except httpx.TransportError as exc:
                raise CloudinaryRetryableError(f"ai_video_analysis file: {exc}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise CloudinaryRetryableError(f"ai_video_analysis file: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise CloudinaryPermanentError(f"ai_video_analysis file: HTTP {response.status_code}")
        payload = response.json()
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("segments"), list):
            return [item for item in payload["segments"] if isinstance(item, dict)]
        raise CloudinaryPermanentError("ai_video_analysis file: expected a JSON array of segments")

    def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None, ok: tuple[int, ...]
    ) -> dict[str, Any]:
        url = BASE.format(cloud=self._creds.cloud_name) + path
        started = time.perf_counter()
        try:
            response = self._http.request(
                method, url, json=json, auth=(self._creds.api_key, self._creds.api_secret)
            )
        except httpx.TransportError as exc:
            raise CloudinaryRetryableError(f"ai_video_analysis: network error: {exc}") from exc
        _ = int((time.perf_counter() - started) * 1000)
        if response.status_code == 429 or response.status_code >= 500:
            raise CloudinaryRetryableError(f"ai_video_analysis: HTTP {response.status_code}")
        if response.status_code not in ok:
            raise CloudinaryPermanentError(
                f"ai_video_analysis: HTTP {response.status_code}: {_error_text(_safe_json(response)) or response.text[:300]}"
            )
        body = _safe_json(response)
        return body if isinstance(body, dict) else {}


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}


def _error_text(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    if error:
        return str(error)[:300]
    return None
