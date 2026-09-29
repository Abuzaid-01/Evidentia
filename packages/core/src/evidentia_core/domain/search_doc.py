"""Build an asset's search document from its current (non-superseded, non-rejected) observations.

Rejected observations are excluded so a reviewer's "no, that's not a pipe" removes it from search.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ObservationText:
    ontology_type: str
    subject: str
    predicate: str
    status: str
    value: dict | None
    confidence: float | None


def _humanize(key: str) -> str:
    return key.replace("_", " ")


def build_search_text(
    *,
    caption: str | None,
    observations: list[ObservationText],
    activity_labels: dict[str, str],
    site_name: str | None,
    filename: str | None,
    note: str | None,
) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    if caption:
        parts.append(caption)
        seen.add(caption.lower())
    for obs in observations:
        if obs.status in {"rejected", "superseded"}:
            continue
        value = obs.value or {}
        if obs.ontology_type == "scene" and value.get("text"):
            text = str(value["text"])
        elif obs.ontology_type == "activity":
            if obs.subject == "other":
                continue
            text = activity_labels.get(obs.subject, _humanize(obs.subject))
        elif obs.ontology_type in {"object", "condition"}:
            text = f"{_humanize(obs.subject)} {_humanize(obs.predicate)}".replace(" visible", "")
        elif obs.ontology_type == "document_text":
            text = str(value.get("text", ""))[:2000]
        elif obs.ontology_type == "people":
            text = "people present"
        else:
            continue
        if text and text.lower() not in seen:
            seen.add(text.lower())
            parts.append(text)
    for extra in (site_name, filename, note):
        if extra:
            parts.append(extra)
    return "\n".join(parts)[:20000]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
