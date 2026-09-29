"""Which media we accept as evidence, and the limits we enforce."""

from __future__ import annotations

from dataclasses import dataclass

from evidentia_core.domain.enums import ResourceType

IMAGE_MIME_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/webp": "webp",
}
VIDEO_MIME_TYPES: dict[str, str] = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}
IMAGE_FORMATS = frozenset({"jpg", "jpeg", "png", "heic", "heif", "webp"})
VIDEO_FORMATS = frozenset({"mp4", "mov", "webm"})


class MediaRejected(ValueError):
    """The declared or actual media violates policy. Never retried."""


@dataclass(frozen=True)
class MediaLimits:
    max_image_bytes: int
    max_video_bytes: int
    max_video_seconds: int


def resource_type_for_mime(mime: str) -> ResourceType:
    mime = mime.lower().strip()
    if mime in IMAGE_MIME_TYPES:
        return ResourceType.IMAGE
    if mime in VIDEO_MIME_TYPES:
        return ResourceType.VIDEO
    allowed = sorted([*IMAGE_MIME_TYPES, *VIDEO_MIME_TYPES])
    raise MediaRejected(f"unsupported media type '{mime}'. Allowed: {', '.join(allowed)}")


def check_declared(mime: str, size_bytes: int, limits: MediaLimits) -> ResourceType:
    resource_type = resource_type_for_mime(mime)
    limit = (
        limits.max_image_bytes if resource_type == ResourceType.IMAGE else limits.max_video_bytes
    )
    if size_bytes <= 0:
        raise MediaRejected("file is empty")
    if size_bytes > limit:
        raise MediaRejected(f"file is {size_bytes} bytes; the limit for {resource_type} is {limit}")
    return resource_type


def check_stored(
    resource_type: ResourceType,
    fmt: str | None,
    size_bytes: int | None,
    duration_seconds: float | None,
    limits: MediaLimits,
) -> None:
    """Re-validate what Cloudinary actually stored (the client could lie about size/type)."""
    fmt = (fmt or "").lower()
    if resource_type == ResourceType.IMAGE:
        if fmt and fmt not in IMAGE_FORMATS:
            raise MediaRejected(f"stored image format '{fmt}' is not allowed")
        if size_bytes and size_bytes > limits.max_image_bytes:
            raise MediaRejected("stored image exceeds the size limit")
    else:
        if fmt and fmt not in VIDEO_FORMATS:
            raise MediaRejected(f"stored video format '{fmt}' is not allowed")
        if size_bytes and size_bytes > limits.max_video_bytes:
            raise MediaRejected("stored video exceeds the size limit")
        if duration_seconds and duration_seconds > limits.max_video_seconds:
            raise MediaRejected(
                f"video is {duration_seconds:.0f}s; the limit is {limits.max_video_seconds}s"
            )
