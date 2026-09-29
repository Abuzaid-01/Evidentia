"""Parse capture time and GPS from Cloudinary's embedded-metadata dictionary.

Cloudinary returns exiftool-style strings, e.g.
  DateTimeOriginal: "2026:08:12 11:42:05", OffsetTimeOriginal: "+05:30"
  GPSLatitude: "28 deg 36' 36.00\\" N"  (or a decimal string, sometimes with a separate Ref key)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

# prime/double-prime characters below are real EXIF notations
_DMS = re.compile(
    r"""^\s*(?P<deg>-?\d+(?:\.\d+)?)\s*(?:deg|°)?\s*
        (?:(?P<min>\d+(?:\.\d+)?)\s*['′]?\s*)?
        (?:(?P<sec>\d+(?:\.\d+)?)\s*(?:["″]|'')?\s*)?
        (?P<ref>[NSEW])?\s*$""",
    re.VERBOSE | re.IGNORECASE,
)
_OFFSET = re.compile(r"^([+-])(\d{2}):?(\d{2})$")

DATE_KEYS = ("DateTimeOriginal", "CreateDate", "DateTimeDigitized", "MediaCreateDate", "DateTime")
CURATED_KEYS = (
    "Make",
    "Model",
    "LensModel",
    "Software",
    "DateTimeOriginal",
    "OffsetTimeOriginal",
    "GPSLatitude",
    "GPSLongitude",
    "GPSAltitude",
    "Orientation",
    "ImageWidth",
    "ImageHeight",
)


@dataclass(frozen=True)
class CaptureInfo:
    capture_time: datetime | None
    latitude: float | None
    longitude: float | None
    curated: dict[str, Any]


def parse_coordinate(value: Any, ref: Any = None) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        number = float(value)
    else:
        match = _DMS.match(str(value))
        if not match:
            return None
        deg = float(match["deg"])
        minutes = float(match["min"] or 0)
        seconds = float(match["sec"] or 0)
        number = abs(deg) + minutes / 60 + seconds / 3600
        if deg < 0:
            number = -number
        ref = match["ref"] or ref
    if ref and str(ref).strip().upper()[:1] in {"S", "W"}:
        number = -abs(number)
    return number


def parse_exif_datetime(value: Any, offset: Any = None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in (
        "%Y:%m:%d %H:%M:%S",
        "%Y:%m:%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(text[:25], fmt)
            break
        except ValueError:
            continue
    else:
        return None
    if parsed.tzinfo is None:
        tz = _parse_offset(offset)
        # Without an offset we cannot know the local zone; keep wall-clock time and mark as UTC.
        parsed = parsed.replace(tzinfo=tz or UTC)
    return parsed


def _parse_offset(value: Any) -> timezone | None:
    if not value:
        return None
    match = _OFFSET.match(str(value).strip())
    if not match:
        return None
    sign = 1 if match[1] == "+" else -1
    return timezone(sign * timedelta(hours=int(match[2]), minutes=int(match[3])))


def extract_capture_info(metadata: dict[str, Any]) -> CaptureInfo:
    capture_time = None
    for key in DATE_KEYS:
        capture_time = parse_exif_datetime(metadata.get(key), metadata.get("OffsetTimeOriginal"))
        if capture_time:
            break
    lat = parse_coordinate(metadata.get("GPSLatitude"), metadata.get("GPSLatitudeRef"))
    lon = parse_coordinate(metadata.get("GPSLongitude"), metadata.get("GPSLongitudeRef"))
    curated = {k: metadata[k] for k in CURATED_KEYS if k in metadata}
    return CaptureInfo(capture_time=capture_time, latitude=lat, longitude=lon, curated=curated)
