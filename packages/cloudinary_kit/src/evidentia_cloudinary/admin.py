"""Admin/Upload API helpers used by the pipeline. All calls are wrapped into typed errors."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

import cloudinary.api
import cloudinary.exceptions as cex
import cloudinary.uploader
import cloudinary.utils

from evidentia_cloudinary.errors import (
    CloudinaryNotFound,
    CloudinaryPermanentError,
    CloudinaryRetryableError,
    translate_sdk_errors,
)


@translate_sdk_errors
def fetch_resource(public_id: str, resource_type: str) -> dict[str, Any]:
    """Authoritative asset details: bytes, format, dimensions, duration, EXIF, pHash, ids."""
    options: dict[str, Any] = {
        "resource_type": resource_type,
        "type": "authenticated",
        "media_metadata": True,
    }
    if resource_type == "image":
        options["phash"] = True
    return dict(cloudinary.api.resource(public_id, **options))


def embedded_metadata(resource: dict[str, Any]) -> dict[str, Any]:
    """Cloudinary returns embedded EXIF/IPTC/XMP under `image_metadata` (images) or
    `video_metadata` / `media_metadata` depending on API version. Normalise to one dict."""
    for key in ("media_metadata", "image_metadata", "video_metadata"):
        value = resource.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


@translate_sdk_errors
def run_ocr(public_id: str) -> dict[str, Any]:
    """OCR Text Detection add-on (Google Vision) on a stored image. Returns the `adv_ocr` block."""
    response = cloudinary.uploader.explicit(
        public_id, type="authenticated", resource_type="image", ocr="adv_ocr"
    )
    return dict(response.get("info", {}).get("ocr", {}).get("adv_ocr", {}))


def ocr_full_text(adv_ocr: dict[str, Any]) -> str:
    for block in adv_ocr.get("data") or []:
        annotations = block.get("textAnnotations") or []
        if annotations:
            return str(annotations[0].get("description", "")).strip()
    return ""


@translate_sdk_errors
def run_auto_tagging(public_id: str, categorization: str, threshold: float) -> list[dict[str, Any]]:
    """Auto-tagging add-on (e.g. google_tagging, imagga_tagging, aws_rek_tagging)."""
    response = cloudinary.uploader.explicit(
        public_id,
        type="authenticated",
        resource_type="image",
        categorization=categorization,
        auto_tagging=threshold,
    )
    block = response.get("info", {}).get("categorization", {}).get(categorization, {})
    return [dict(item) for item in block.get("data") or []]


@translate_sdk_errors
def add_tags(public_id: str, resource_type: str, tags: Iterable[str]) -> None:
    for tag in tags:
        cloudinary.uploader.add_tag(
            tag, [public_id], type="authenticated", resource_type=resource_type
        )


@translate_sdk_errors
def add_context(public_id: str, resource_type: str, context: dict[str, str]) -> None:
    """Merge keys into the asset's contextual metadata (visible in the Media Library)."""
    cloudinary.uploader.add_context(
        context, [public_id], type="authenticated", resource_type=resource_type
    )


@translate_sdk_errors
def update_structured_metadata(public_id: str, resource_type: str, values: dict[str, str]) -> None:
    cloudinary.uploader.update_metadata(
        values, [public_id], type="authenticated", resource_type=resource_type
    )


@translate_sdk_errors
def request_auto_transcription(public_id: str) -> None:
    """Ask Cloudinary to transcribe speech on an authenticated video (`auto_transcription`).

    The transcript arrives later as a raw file named `{public_id}.transcript`.
    """
    cloudinary.uploader.explicit(
        public_id,
        type="authenticated",
        resource_type="video",
        auto_transcription=True,
    )


@translate_sdk_errors
def fetch_transcript_json(public_id: str) -> list[dict[str, Any]]:
    """Download a `.transcript` raw file. Tries public upload, then authenticated delivery."""
    import httpx

    for delivery_type in ("upload", "authenticated"):
        try:
            info = cloudinary.api.resource(public_id, resource_type="raw", type=delivery_type)
        except cex.NotFound:
            continue
        url = info.get("secure_url")
        if delivery_type == "authenticated":
            url = cloudinary.utils.private_download_url(
                public_id,
                "",
                resource_type="raw",
                type="authenticated",
                expires_at=int(time.time()) + 300,
            )
        if not url:
            continue
        response = httpx.get(url, timeout=30)
        if response.status_code == 404:
            continue
        if response.status_code == 429 or response.status_code >= 500:
            raise CloudinaryRetryableError(f"transcript download: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise CloudinaryPermanentError(f"transcript download: HTTP {response.status_code}")
        payload = response.json()
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("segments"), list):
            return [item for item in payload["segments"] if isinstance(item, dict)]
        raise CloudinaryPermanentError("transcript file was not a JSON array")
    raise CloudinaryNotFound(f"no transcript for {public_id}")


@translate_sdk_errors
def video_frame(public_id: str, transformation: str) -> str | None:
    """Generate one derived frame via the explicit API (works when strict transformations are on).

    Returns the derived secure URL, or None when Cloudinary did not produce one.
    """
    response = cloudinary.uploader.explicit(
        public_id,
        type="authenticated",
        resource_type="video",
        eager=f"{transformation}/jpg",
        eager_async=False,
    )
    eager = (response.get("eager") or [None])[0] or {}
    url = eager.get("secure_url")
    return str(url) if url else None


def phash_to_int(phash: str | None) -> int | None:
    """Cloudinary returns pHash as 16 hex chars (64 bits). Store as a signed BIGINT."""
    if not phash:
        return None
    value = int(phash, 16)
    return value - (1 << 64) if value >= (1 << 63) else value


def hamming_distance(a: int, b: int) -> int:
    return ((a ^ b) & ((1 << 64) - 1)).bit_count()


@translate_sdk_errors
def upload_authenticated_raw(
    data: bytes,
    public_id: str,
    *,
    asset_folder: str,
    tags: Iterable[str] = (),
    context: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Store a generated file (e.g. a report PDF) privately. `public_id` includes the extension,
    as Cloudinary requires for raw files. Overwrites the same path, so retries are idempotent."""
    response = cloudinary.uploader.upload(
        data,
        resource_type="raw",
        type="authenticated",
        public_id=public_id,
        asset_folder=asset_folder,
        overwrite=True,
        invalidate=True,
        tags=list(tags),
        context=context or {},
    )
    return dict(response)
