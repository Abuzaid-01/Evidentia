"""Turn raw model text into a validated VisionExtraction, or fail loudly."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from evidentia_ai.schemas import VisionExtraction

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class ExtractionInvalid(ValueError):
    """The model answered, but not with a valid extraction."""


def extract_json_object(text: str) -> dict[str, Any]:
    candidates = [m.group(1) for m in _FENCE.finditer(text)] or [text]
    for candidate in candidates:
        candidate = candidate.strip()
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            continue
        try:
            value = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ExtractionInvalid("no JSON object found in model output")


_SCENES = {
    "construction_site",
    "infrastructure",
    "landscape",
    "vegetation",
    "people_activity",
    "meeting_or_training",
    "document_or_sign",
    "indoor",
    "other",
}
_SENSITIVE = {
    "faces",
    "children",
    "license_plates",
    "personal_documents",
    "private_residence_interior",
}
_LIMITS = {"activities": 6, "objects": 20, "conditions": 10, "quality_issues": 6, "uncertainty": 6}


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if 1 < number <= 100:  # models sometimes answer in percent
        number /= 100
    return min(1.0, max(0.0, number))


def _bbox(value: Any) -> dict[str, float] | None:
    try:
        box = {k: float(value[k]) for k in ("x", "y", "w", "h")}
    except (TypeError, KeyError, ValueError):
        return None
    ok = all(0 <= box[k] <= 1 for k in ("x", "y")) and all(0 < box[k] <= 1 for k in ("w", "h"))
    return box if ok else None


def coerce_extraction(data: dict[str, Any]) -> dict[str, Any]:
    """Repair common, harmless model deviations so one quirk doesn't discard a whole answer.

    Only *shape* is repaired (ranges, list lengths, unknown enum values). Anything that would change
    meaning (e.g. an unknown activity key) is still handled explicitly by `validate_extraction`.
    """
    d = dict(data)
    d["caption"] = str(d.get("caption") or "").strip()[:500]
    if d.get("scene_type") not in _SCENES:
        d["scene_type"] = "other"
    for key, limit in _LIMITS.items():
        value = d.get(key)
        d[key] = value[:limit] if isinstance(value, list) else []
    for key in ("activities", "objects", "conditions"):
        items = []
        for item in d[key]:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["confidence"] = _confidence(item.get("confidence"))
            for text_key, limit in (
                ("rationale", 400),
                ("name", 80),
                ("subject", 80),
                ("condition", 80),
            ):
                if text_key in item:
                    item[text_key] = str(item[text_key])[:limit]
            if "name" in item:
                item["name"] = item["name"].strip().lower().replace(" ", "_")
            if "count" in item and not (isinstance(item["count"], int) and item["count"] >= 0):
                item["count"] = None
            if key == "activities":
                item.setdefault("rationale", "")
                item["region"] = _bbox(item.get("region")) if item.get("region") else None
            items.append(item)
        d[key] = items
    d["quality_issues"] = [str(x)[:200] for x in d["quality_issues"]]
    d["uncertainty"] = [str(x)[:200] for x in d["uncertainty"]]
    d["sensitive_flags"] = [f for f in d.get("sensitive_flags") or [] if f in _SENSITIVE]
    d["people_present"] = bool(d.get("people_present"))
    d["text_present"] = bool(d.get("text_present"))
    count = d.get("people_count_estimate")
    d["people_count_estimate"] = count if isinstance(count, int) and count >= 0 else None
    return d


def validate_extraction(data: dict[str, Any], allowed_activities: set[str]) -> VisionExtraction:
    try:
        extraction = VisionExtraction.model_validate(coerce_extraction(data))
    except ValidationError as exc:
        raise ExtractionInvalid(f"schema validation failed: {exc.error_count()} errors") from exc

    # Unknown activity keys are not silently trusted: they become 'other' with the original noted.
    cleaned = []
    for candidate in extraction.activities:
        if candidate.activity not in allowed_activities and candidate.activity != "other":
            candidate = candidate.model_copy(
                update={
                    "rationale": f"[model proposed '{candidate.activity}'] {candidate.rationale}"[
                        :400
                    ],
                    "activity": "other",
                }
            )
        cleaned.append(candidate)
    return extraction.model_copy(update={"activities": cleaned})


def parse_extraction(text: str, allowed_activities: set[str]) -> VisionExtraction:
    return validate_extraction(extract_json_object(text), allowed_activities)
