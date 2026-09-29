"""The canonical output schema for visual evidence extraction.

Every provider must produce exactly this structure. We validate it with Pydantic before anything is
persisted; a response that fails validation is never stored as an observation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "vision-extract/1"

SensitiveFlag = Literal[
    "faces", "children", "license_plates", "personal_documents", "private_residence_interior"
]
SceneType = Literal[
    "construction_site",
    "infrastructure",
    "landscape",
    "vegetation",
    "people_activity",
    "meeting_or_training",
    "document_or_sign",
    "indoor",
    "other",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class BBox(_Strict):
    """Normalized bounding box, 0..1 relative to image width/height."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class ActivityCandidate(_Strict):
    activity: str = Field(description="One of the allowed activity keys, or 'other'")
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(max_length=400, description="Visible cues that support this activity")
    region: BBox | None = None


class ObjectFinding(_Strict):
    name: str = Field(max_length=80, description="snake_case object name, e.g. water_tank")
    count: int | None = Field(default=None, ge=0, le=10000)
    confidence: float = Field(ge=0, le=1)


class ConditionFinding(_Strict):
    subject: str = Field(max_length=80)
    condition: str = Field(max_length=80, description="e.g. under_construction, completed, damaged")
    confidence: float = Field(ge=0, le=1)


class VisionExtraction(_Strict):
    caption: str = Field(
        min_length=3, max_length=500, description="One factual sentence describing what is visible"
    )
    scene_type: SceneType = "other"
    activities: list[ActivityCandidate] = Field(default_factory=list, max_length=6)
    objects: list[ObjectFinding] = Field(default_factory=list, max_length=20)
    conditions: list[ConditionFinding] = Field(default_factory=list, max_length=10)
    people_present: bool = False
    people_count_estimate: int | None = Field(default=None, ge=0, le=10000)
    text_present: bool = Field(default=False, description="Readable signs/documents are visible")
    sensitive_flags: list[SensitiveFlag] = Field(default_factory=list)
    quality_issues: list[str] = Field(default_factory=list, max_length=6)
    uncertainty: list[str] = Field(
        default_factory=list, max_length=6, description="What cannot be determined from pixels"
    )

    @field_validator("quality_issues", "uncertainty")
    @classmethod
    def _short(cls, values: list[str]) -> list[str]:
        return [v[:200] for v in values if v]


def json_schema() -> dict[str, Any]:
    """A compact JSON schema to embed in prompts (providers that support it also get it natively)."""
    schema = VisionExtraction.model_json_schema()
    return _inline_refs(schema)


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Some providers (and Cloudinary's prompt convention) handle `$ref` poorly: inline them."""
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved
