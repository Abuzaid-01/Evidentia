"""Before/after rules: pairing windows, ranking, plain-language change summaries and limitations.

Pure functions over the measurements produced by `evidentia_ml.before_after`. Limitations are
derived by rules (never written by a model) and worded without digits, like report limitations,
so they can be shown anywhere without breaking the "no unsourced numbers" rule.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

MIN_GAP_DAYS = 7  # a before/after pair must be at least this far apart
DEFAULT_PER_ANCHOR = 3  # candidate "before" photos kept per "after" photo
DEFAULT_MAX_DISTANCE_M = 250.0
SIMILARITY_WEIGHT = 0.35
GEOMETRY_WEIGHT = 0.65
VERIFIED_FLOOR = 0.1  # every geometrically verified pair outranks every pair that failed

# geometry grades
STRONG_INLIERS, STRONG_RATIO, STRONG_OVERLAP = 60, 0.5, 0.7
WEAK_INLIERS, WEAK_RATIO = 30, 0.35
PARTIAL_OVERLAP = 0.6
VIEWPOINT_ROTATION_DEG, VIEWPOINT_SCALE, VIEWPOINT_PERSPECTIVE = 10.0, 1.3, 0.15
GREEN_SHIFT = 0.02  # share of the view; below this, colour-index noise on unchanged scenes
LIGHTING_SHIFT = 25.0  # mean luminance difference (0..255) before normalisation
SEASON_GAP_DAYS = 60
LOW_RESOLUTION_PX = 640
LOW_QUALITY = 0.4

Grade = Literal["strong", "partial", "none"]
_WEAK_TIME_SOURCES = {"upload", "user", "none"}


# --- windows ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Windows:
    baseline_from: date | None
    baseline_to: date | None
    endline_from: date | None
    endline_to: date | None


def default_windows(capture_dates: Sequence[date]) -> Windows | None:
    """Without explicit windows, split the site's capture dates at the midpoint of their range:
    earlier photos are baseline candidates, later ones endline candidates."""
    if len(capture_dates) < 2:
        return None
    first, last = min(capture_dates), max(capture_dates)
    if (last - first).days < MIN_GAP_DAYS:
        return None
    middle = first + (last - first) / 2
    return Windows(first, middle, middle + timedelta(days=1), last)


def days_apart(before: datetime | None, after: datetime | None) -> int | None:
    if before is None or after is None:
        return None
    return (after.date() - before.date()).days


def _season_gap(before: datetime, after: datetime) -> bool:
    diff = abs(before.timetuple().tm_yday - after.timetuple().tm_yday)
    return min(diff, 365 - diff) >= SEASON_GAP_DAYS


# --- scoring ---------------------------------------------------------------------------------------


def alignment_grade(alignment: Mapping[str, Any] | None) -> Grade:
    if not alignment or not alignment.get("ok"):
        return "none"
    if (
        alignment.get("inliers", 0) >= STRONG_INLIERS
        and alignment.get("inlier_ratio", 0) >= STRONG_RATIO
        and alignment.get("overlap", 0) >= STRONG_OVERLAP
    ):
        return "strong"
    return "partial"


def geometry_score(alignment: Mapping[str, Any] | None) -> float:
    """0..1: how convincingly the photos show the same scene from a comparable viewpoint."""
    if not alignment or not alignment.get("ok"):
        return 0.0
    inliers = min(1.0, float(alignment.get("inliers", 0)) / STRONG_INLIERS)
    ratio = max(0.0, min(1.0, float(alignment.get("inlier_ratio", 0))))
    overlap = max(0.0, min(1.0, float(alignment.get("overlap", 0))))
    return inliers * ratio * overlap**0.5


def rank_score(similarity: float | None, alignment: Mapping[str, Any] | None) -> float:
    """SigLIP proposes, geometry decides. Before analysis only similarity is known; afterwards a
    pair that fails geometric verification sinks below every pair that passes it."""
    sim = max(0.0, min(1.0, similarity)) if similarity is not None else None
    if alignment is None:
        return round(SIMILARITY_WEIGHT * (sim or 0.0), 4)
    if not alignment.get("ok"):
        return round(0.09 * (sim or 0.0), 4)  # always below VERIFIED_FLOOR
    geo = geometry_score(alignment)
    blended = geo if sim is None else SIMILARITY_WEIGHT * sim + GEOMETRY_WEIGHT * geo
    return round(VERIFIED_FLOOR + (1 - VERIFIED_FLOOR) * blended, 4)


# --- plain language ------------------------------------------------------------------------------------


def _share_words(share: float) -> str:
    if share < 0.02:
        return "almost none"
    if share < 0.1:
        return "a small part"
    if share < 0.3:
        return "a noticeable part"
    if share < 0.6:
        return "a large part"
    return "most"


def change_summary(change: Mapping[str, Any] | None, alignment: Mapping[str, Any] | None) -> str:
    """One digit-free sentence describing the visible change."""
    if not alignment or not alignment.get("ok"):
        return "The photos could not be aligned, so visible change was not measured."
    if not change:
        return "Visible change was not measured."
    parts = [
        f"Visible change across {_share_words(float(change['changed_share']))} of the shared view"
    ]
    delta = float(change["green_cover_after"]) - float(change["green_cover_before"])
    if delta >= GREEN_SHIFT:
        parts.append("green cover increased")
    elif delta <= -GREEN_SHIFT:
        parts.append("green cover decreased")
    else:
        parts.append("green cover about the same")
    return "; ".join(parts) + "."


# --- limitations -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PhotoFacts:
    capture_time: datetime | None
    capture_time_source: str
    has_location: bool
    width: int | None
    height: int | None
    quality_score: float | None = None


ALWAYS = (
    "Visible change between two photographs shows only what the camera captured on two dates; "
    "it is not by itself evidence of outcomes for people or the environment."
)


def derive_limitations(
    alignment: Mapping[str, Any] | None,
    change: Mapping[str, Any] | None,
    before: PhotoFacts,
    after: PhotoFacts,
    distance_m: float | None,
) -> list[str]:
    out = [ALWAYS]
    ok = bool(alignment and alignment.get("ok"))
    if not ok:
        out.append(
            "The photos could not be aligned; they may not show the same viewpoint, so no change "
            "was measured and the comparison rests on human judgement alone."
        )
    else:
        assert alignment is not None
        if (
            alignment.get("inliers", 0) < WEAK_INLIERS
            or alignment.get("inlier_ratio", 0) < WEAK_RATIO
        ):
            out.append(
                "Alignment rests on few matching features; small misalignments can show up as "
                "false change."
            )
        if alignment.get("overlap", 0) < PARTIAL_OVERLAP:
            out.append(
                "The photos overlap only partly; change is measured only in the shared view."
            )
        rotation = abs(float(alignment.get("rotation_deg") or 0))
        scale = float(alignment.get("scale") or 1) or 1.0
        if (
            rotation > VIEWPOINT_ROTATION_DEG
            or max(scale, 1 / scale) > VIEWPOINT_SCALE
            or float(alignment.get("perspective") or 0) > VIEWPOINT_PERSPECTIVE
        ):
            out.append(
                "The camera position differs between the photos; alignment corrects the plane of "
                "the scene, but objects at other depths can appear as false change (parallax)."
            )
    if change:
        if abs(float(change.get("luminance_shift") or 0)) > LIGHTING_SHIFT:
            out.append(
                "Lighting differs between the photos; brightness was normalised, but shadows and "
                "sky can still register as change."
            )
        out.append(
            "Green cover is estimated with a colour index (Excess Green); green paint, tarpaulins "
            "or strong shadows can be mistaken for vegetation or hide it."
        )
    if before.capture_time and after.capture_time:
        if _season_gap(before.capture_time, after.capture_time):
            out.append(
                "The photos were taken in different seasons; vegetation and water levels can "
                "change seasonally, independent of the programme."
            )
        if after.capture_time <= before.capture_time:
            out.append("The after photo is not dated later than the before photo.")
    else:
        out.append("At least one photo has no capture date, so the time between them is unknown.")
    if (
        before.capture_time_source in _WEAK_TIME_SOURCES
        or after.capture_time_source in _WEAK_TIME_SOURCES
    ):
        out.append(
            "At least one capture date comes from the upload time or the contributor rather than "
            "the camera."
        )
    if not (before.has_location and after.has_location):
        out.append(
            "At least one photo has no GPS position; the pairing relies on the site assigned at "
            "upload."
        )
    elif distance_m is not None and distance_m > DEFAULT_MAX_DISTANCE_M:
        out.append("The GPS positions of the photos are far apart for a repeat photograph.")
    sizes = [s for s in (before.width, before.height, after.width, after.height) if s]
    if sizes and min(sizes) < LOW_RESOLUTION_PX:
        out.append("At least one photo is low resolution; small changes may be missed.")
    if any(q is not None and q < LOW_QUALITY for q in (before.quality_score, after.quality_score)):
        out.append("At least one photo scored low on image quality (blur, noise or exposure).")
    return out
