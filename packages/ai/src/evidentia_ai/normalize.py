"""Map validated model output to typed observation drafts (pure functions, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evidentia_core.domain.enums import OntologyType

from evidentia_ai.schemas import VisionExtraction


@dataclass(frozen=True)
class ObservationDraft:
    ontology_type: OntologyType
    subject: str
    predicate: str
    confidence: float | None = None
    value: dict[str, Any] = field(default_factory=dict)
    evidence_span: dict[str, Any] | None = None


def _frame_span(frame_offset: str | None) -> dict[str, Any] | None:
    return {"type": "frame", "offset": frame_offset} if frame_offset else None


def from_extraction(
    extraction: VisionExtraction,
    *,
    frame_offset: str | None = None,
    span: dict[str, Any] | None = None,
) -> list[ObservationDraft]:
    """frame_offset is set when the image is one frame of a video (e.g. '50p').

    `span` is a timestamped segment ({type, start_ms, end_ms}) and replaces the frame offset.
    """
    base_span = span if span is not None else _frame_span(frame_offset)
    drafts = [
        ObservationDraft(
            OntologyType.SCENE,
            "image",
            "caption",
            value={"text": extraction.caption, "scene_type": extraction.scene_type},
            evidence_span=base_span,
        )
    ]
    for activity in extraction.activities:
        span = base_span
        if activity.region:
            span = {
                "type": "bbox",
                **activity.region.model_dump(),
                **({"frame": frame_offset} if frame_offset else {}),
            }
        drafts.append(
            ObservationDraft(
                OntologyType.ACTIVITY,
                activity.activity,
                "depicted",
                confidence=activity.confidence,
                value={"rationale": activity.rationale},
                evidence_span=span,
            )
        )
    for obj in extraction.objects:
        drafts.append(
            ObservationDraft(
                OntologyType.OBJECT,
                obj.name,
                "visible",
                confidence=obj.confidence,
                value={"count": obj.count} if obj.count is not None else {},
                evidence_span=base_span,
            )
        )
    for condition in extraction.conditions:
        drafts.append(
            ObservationDraft(
                OntologyType.CONDITION,
                condition.subject,
                condition.condition,
                confidence=condition.confidence,
                evidence_span=base_span,
            )
        )
    if extraction.people_present:
        drafts.append(
            ObservationDraft(
                OntologyType.PEOPLE,
                "people",
                "present",
                value={"count_estimate": extraction.people_count_estimate},
                evidence_span=base_span,
            )
        )
    for flag in extraction.sensitive_flags:
        drafts.append(
            ObservationDraft(OntologyType.SENSITIVE, flag, "detected", evidence_span=base_span)
        )
    for issue in extraction.quality_issues:
        drafts.append(
            ObservationDraft(OntologyType.QUALITY, "image", "issue", value={"issue": issue})
        )
    return drafts


def caption_draft(caption: str, provider_label: str) -> ObservationDraft:
    return ObservationDraft(
        OntologyType.SCENE, "image", "caption", value={"text": caption, "via": provider_label}
    )


def tagging_drafts(tag_names: list[str]) -> list[ObservationDraft]:
    """Cloudinary AI Vision tagging answers yes/no questions without a confidence score."""
    return [
        ObservationDraft(
            OntologyType.ACTIVITY, name, "tagged", value={"method": "ai_vision_tagging"}
        )
        for name in tag_names
    ]


def ocr_draft(text: str) -> ObservationDraft:
    return ObservationDraft(
        OntologyType.DOCUMENT_TEXT,
        "visible_text",
        "extracted",
        # OCR text is untrusted input: it is stored and searchable, but never fed back into prompts
        # as instructions.
        value={"text": text[:5000], "untrusted": True},
    )


def quality_draft(analysis: dict[str, Any]) -> ObservationDraft:
    return ObservationDraft(
        OntologyType.QUALITY, "image", "quality_analysis", value={"analysis": analysis}
    )


def auto_tag_drafts(tags: list[dict[str, Any]], source: str) -> list[ObservationDraft]:
    drafts = []
    for tag in tags:
        name = str(tag.get("tag", "")).strip().lower().replace(" ", "_")[:80]
        if name:
            confidence = tag.get("confidence")
            drafts.append(
                ObservationDraft(
                    OntologyType.OBJECT,
                    name,
                    "tagged",
                    confidence=float(confidence) if confidence is not None else None,
                    value={"method": source},
                )
            )
    return drafts
