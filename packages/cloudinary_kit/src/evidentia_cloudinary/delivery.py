"""Delivery URLs for `authenticated` evidence.

* Derived renditions: signed URLs using a named transformation. The signature pins the exact
  transformation, so a viewer cannot edit the URL to fetch the original or another rendition.
  Note: signed URLs for authenticated assets do NOT expire (see PLAN.md §2 #10). We only hand
  out renditions this way, never originals.
* Originals: short-lived `private_download_url` (expires_at), issued per request after auth.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cloudinary.utils

from evidentia_cloudinary.transformations import NamedTransformation, for_resource


@dataclass(frozen=True)
class DeliveryUrl:
    url: str
    variant: str
    transformation: str
    named_transformation: str | None
    format: str | None
    expires_at: int | None = None


def _transformation_for(nt: NamedTransformation, named: bool) -> dict[str, str]:
    return {"transformation": nt.name} if named else {"raw_transformation": nt.definition}


def rendition_url(
    public_id: str,
    resource_type: str,
    variant: str,
    *,
    use_named: bool = True,
    version: int | None = None,
) -> DeliveryUrl:
    table = for_resource(resource_type)
    if variant not in table:
        raise ValueError(f"unknown variant '{variant}' for {resource_type}")
    nt = table[variant]
    options: dict[str, object] = {
        "resource_type": resource_type,
        "type": "authenticated",
        "sign_url": True,
        "secure": True,
        **_transformation_for(nt, use_named),
    }
    if nt.format:
        options["format"] = nt.format
    if version:
        options["version"] = version
    url, _ = cloudinary.utils.cloudinary_url(public_id, **options)
    return DeliveryUrl(
        url=url,
        variant=variant,
        transformation=nt.definition,
        named_transformation=nt.name if use_named else None,
        format=nt.format,
    )


def original_download_url(
    public_id: str, resource_type: str, fmt: str, *, ttl_seconds: int = 300
) -> DeliveryUrl:
    expires_at = int(time.time()) + ttl_seconds
    url = cloudinary.utils.private_download_url(
        public_id,
        fmt,
        resource_type=resource_type,
        type="authenticated",
        expires_at=expires_at,
    )
    return DeliveryUrl(
        url=url,
        variant="original",
        transformation="",
        named_transformation=None,
        format=fmt,
        expires_at=expires_at,
    )


def frame_url(public_id: str, seconds: float) -> DeliveryUrl:
    """A signed JPEG of one video frame (`so_<t>`). Used when AI Video Analysis is unavailable.

    This is a dynamic transformation, so an account with strict transformations enabled will
    reject the URL. The pipeline then asks the Admin API to generate the frame instead.
    """
    return _signed_video(public_id, _frame_raw(seconds), fmt="jpg", variant="keyframe")


def clip_url(
    public_id: str, start_ms: int, end_ms: int, *, version: int | None = None
) -> DeliveryUrl:
    """Signed `so_`/`eo_` clip of a video span. The transformation string is the lineage."""
    raw = _clip_raw(start_ms, end_ms)
    return _signed_video(public_id, raw, fmt="mp4", variant="clip", version=version)


def stream_url(public_id: str, *, version: int | None = None) -> DeliveryUrl:
    """Signed adaptive stream (`sp_auto`) for the Cloudinary video player."""
    options: dict[str, object] = {
        "resource_type": "video",
        "type": "authenticated",
        "sign_url": True,
        "secure": True,
        "streaming_profile": "auto",
        "format": "m3u8",
    }
    if version:
        options["version"] = version
    url, _ = cloudinary.utils.cloudinary_url(public_id, **options)
    return DeliveryUrl(
        url=url,
        variant="stream",
        transformation="sp_auto",
        named_transformation=None,
        format="m3u8",
    )


def _frame_raw(seconds: float) -> str:
    text = f"{seconds:.2f}".rstrip("0").rstrip(".") or "0"
    return f"so_{text}/c_limit,w_1280,h_1280/q_auto:good"


def _clip_raw(start_ms: int, end_ms: int) -> str:
    def num(ms: int) -> str:
        text = f"{ms / 1000:.2f}".rstrip("0").rstrip(".")
        return text or "0"

    return f"so_{num(start_ms)},eo_{num(end_ms)}/c_limit,w_1280,h_720/q_auto"


def _signed_video(
    public_id: str, raw: str, *, fmt: str, variant: str, version: int | None = None
) -> DeliveryUrl:
    options: dict[str, object] = {
        "resource_type": "video",
        "type": "authenticated",
        "sign_url": True,
        "secure": True,
        "raw_transformation": raw,
        "format": fmt,
    }
    if version:
        options["version"] = version
    url, _ = cloudinary.utils.cloudinary_url(public_id, **options)
    return DeliveryUrl(
        url=url,
        variant=variant,
        transformation=raw,
        named_transformation=None,
        format=fmt,
    )


def raw_download_url(public_id: str, *, ttl_seconds: int = 300) -> DeliveryUrl:
    """Expiring download link for a private raw file (the extension is part of the public_id)."""
    expires_at = int(time.time()) + ttl_seconds
    url = cloudinary.utils.private_download_url(
        public_id, "", resource_type="raw", type="authenticated", expires_at=expires_at
    )
    return DeliveryUrl(
        url=url,
        variant="download",
        transformation="",
        named_transformation=None,
        format=public_id.rsplit(".", 1)[-1] if "." in public_id else None,
        expires_at=expires_at,
    )
