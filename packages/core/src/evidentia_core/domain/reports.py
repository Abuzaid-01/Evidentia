"""Report rules: citation-constrained narrative, derived limitations and reproducible manifests.

Rules for every narrative sentence (checked after generation, after human edits, and at publish):
  * it cites at least one approved claim or sourced metric included in the report
  * every citation points at a claim/metric that is actually in the report
  * every number equals the value of a cited metric, or of a metric linked to a cited claim

A published snapshot is a manifest (canonical JSON) plus the HTML rendered purely from it. Both are
hashed, so anyone can re-render the manifest later and prove the report has not changed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from evidentia_core.domain.claims import numbers_in
from evidentia_core.domain.enums import CitationKind, ClaimType

# /2: timeline of photo captures and approvals, AI models used (rendered by report_v2 template)
MANIFEST_VERSION = "report-manifest/2"

# Narrative sections are prose (checked); the other sections are rendered from structured data.
NARRATIVE_SECTIONS: tuple[str, ...] = ("summary", "overview")
SECTIONS: tuple[tuple[str, str], ...] = (
    ("summary", "Summary"),
    ("overview", "Programme overview"),
    ("timeline", "Timeline"),
    ("gallery", "Evidence gallery"),
    ("metrics", "Metrics"),
    ("limitations", "Limitations"),
    ("appendix", "Appendix: claims, evidence and provenance"),
)

MAX_SENTENCE_CHARS = 600
CLAIM_TYPE_ORDER = {
    ClaimType.OUTCOME: 0,
    ClaimType.METRIC: 1,
    ClaimType.PROGRESS: 2,
    ClaimType.DESCRIPTIVE: 3,
}


# --- citations & sentence checks ---------------------------------------------------------------


@dataclass(frozen=True)
class Citation:
    kind: CitationKind
    id: str

    def as_dict(self) -> dict[str, str]:
        return {"type": self.kind.value, "id": self.id}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> Citation:
        return cls(CitationKind(str(raw["type"])), str(raw["id"]))


@dataclass(frozen=True)
class CitationContext:
    """What a report may cite: included claims (with their linked metrics) and sourced metrics."""

    claim_metrics: Mapping[str, frozenset[str]]
    metric_values: Mapping[str, Decimal]

    def allowed_numbers(self, cites: Iterable[Citation]) -> set[Decimal]:
        metric_ids: set[str] = set()
        for cite in cites:
            if cite.kind == CitationKind.METRIC:
                metric_ids.add(cite.id)
            else:
                metric_ids |= self.claim_metrics.get(cite.id, frozenset())
        return {self.metric_values[m].normalize() for m in metric_ids if m in self.metric_values}


@dataclass(frozen=True)
class SentenceProblem:
    section: str
    index: int
    text: str
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "index": self.index,
            "text": self.text,
            "problems": self.problems,
        }


# Split after . ! ? when followed by whitespace and a new sentence (capital, digit, quote, bracket).
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(\[])")


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(text.strip()) if part.strip()]


def sentence_problems(text: str, cites: Sequence[Citation], ctx: CitationContext) -> list[str]:
    problems: list[str] = []
    if not text.strip():
        return ["Empty sentence"]
    if len(text) > MAX_SENTENCE_CHARS:
        problems.append(f"Sentence is longer than {MAX_SENTENCE_CHARS} characters")
    if not cites:
        problems.append("Sentence has no citation")
    for cite in cites:
        known = (
            cite.id in ctx.claim_metrics
            if cite.kind == CitationKind.CLAIM
            else cite.id in ctx.metric_values
        )
        if not known:
            problems.append(f"Cites a {cite.kind.value} that is not in this report ({cite.id})")
    allowed = ctx.allowed_numbers(cites)
    for raw in numbers_in(text):
        value = Decimal(raw.replace(",", ""))
        if value.normalize() not in allowed:
            problems.append(f"Number '{raw}' does not match any cited metric")
    return problems


def normalize_narrative(sections: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Canonical shape: {section: [{text, cites:[{type,id}]}]}, one sentence per item.

    An item holding several sentences is split and every part keeps the item's citations, so the
    rule "every sentence has a citation" holds per sentence, not per paragraph.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for section in NARRATIVE_SECTIONS:
        items: list[dict[str, Any]] = []
        for item in sections.get(section) or []:
            cites = [Citation.parse(c).as_dict() for c in item.get("cites") or []]
            unique = list({(c["type"], c["id"]): c for c in cites}.values())
            for sentence in split_sentences(str(item.get("text", ""))):
                items.append({"text": sentence, "cites": unique})
        out[section] = items
    return out


def check_narrative(
    sections: Mapping[str, Sequence[Mapping[str, Any]]], ctx: CitationContext
) -> list[SentenceProblem]:
    found = []
    for section in NARRATIVE_SECTIONS:
        for index, item in enumerate(sections.get(section) or []):
            cites = [Citation.parse(c) for c in item.get("cites") or []]
            problems = sentence_problems(str(item.get("text", "")), cites, ctx)
            if problems:
                found.append(SentenceProblem(section, index, str(item.get("text", "")), problems))
    return found


def has_content(sections: Mapping[str, Sequence[Any]] | None) -> bool:
    return bool(sections) and any(sections.get(s) for s in NARRATIVE_SECTIONS)  # type: ignore[union-attr]


# --- periods ------------------------------------------------------------------------------------------


def periods_overlap(
    start: date | None, end: date | None, other_start: date | None, other_end: date | None
) -> bool:
    """Open-ended periods overlap everything on their open side."""
    if start and other_end and other_end < start:
        return False
    return not (end and other_start and other_start > end)


# --- limitations (derived from the manifest, never written by a model) ---------------------------------


_WEAK_TIME_SOURCES = {"upload", "user", "none"}
_VISUAL_CLAIMS = {ClaimType.DESCRIPTIVE.value, ClaimType.PROGRESS.value}


def derive_limitations(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Deterministic, cited limitation sentences. Worded without digits so they always pass the
    number rule; the citations name the claims and metrics concerned."""
    claims = manifest.get("claims") or []
    by_ref = {c["ref"]: c for c in claims}
    evidence = {e["ref"]: e for e in manifest.get("evidence") or []}
    assets = {a["ref"]: a for a in manifest.get("assets") or []}

    def cite(refs: Iterable[str], kind: CitationKind) -> list[dict[str, str]]:
        items = claims if kind == CitationKind.CLAIM else manifest.get("metrics") or []
        ids = {i["ref"]: i["id"] for i in items}
        return [{"type": kind.value, "id": ids[r]} for r in sorted(set(refs), key=_ref_key)]

    out: list[dict[str, Any]] = []

    def add(text: str, refs: Iterable[str], kind: CitationKind = CitationKind.CLAIM) -> None:
        refs = list(refs)
        if refs:
            out.append({"text": text, "cites": cite(refs, kind)})

    add(
        "Some claims describe only what is visible in field media; visible change is not by "
        "itself evidence of outcomes for people or the environment.",
        (c["ref"] for c in claims if c["claim_type"] in _VISUAL_CLAIMS),
    )
    verdicts: dict[str, list[str]] = {}
    for c in claims:
        verdicts.setdefault((c.get("validation") or {}).get("verdict") or "none", []).append(
            c["ref"]
        )
    add(
        "No automated validator checked some claims; their approval rests on human review of the "
        "linked evidence.",
        verdicts.get("not_checked", []) + verdicts.get("none", []),
    )
    add(
        "Automated validation found some claims only partially supported; reviewers approved them "
        "and their notes are listed in the appendix.",
        verdicts.get("partially_supported", []),
    )
    add(
        "Automated validation did not support some claims; reviewers overrode it with the reasons "
        "recorded in the appendix.",
        verdicts.get("not_supported", []),
    )
    add(
        "Some claims rest on before and after photographs of the same place; such comparisons "
        "show visible change only and list their own limitations in the evidence gallery.",
        (
            e["claim_ref"]
            for e in evidence.values()
            if e.get("pair_ref") and e["claim_ref"] in by_ref
        ),
    )
    weak_time = set()
    for ref, item in evidence.items():
        asset = assets.get(item["asset_ref"])
        if asset and asset.get("capture_time_source") in _WEAK_TIME_SOURCES:
            weak_time.add(evidence[ref]["claim_ref"])
    add(
        "Some supporting media has no camera timestamp; its capture date comes from the upload "
        "time or from the contributor.",
        (r for r in weak_time if r in by_ref),
    )
    metrics = manifest.get("metrics") or []
    add(
        "Some metrics were counted from media rather than measured independently.",
        (m["ref"] for m in metrics if m["source_type"] == "visual_count"),
        CitationKind.METRIC,
    )
    add(
        "Some metrics come from third-party sources that the programme team did not measure "
        "itself.",
        (m["ref"] for m in metrics if m["source_type"] == "third_party"),
        CitationKind.METRIC,
    )
    return out


def _ref_key(ref: str) -> tuple[str, int]:
    prefix = ref.rstrip("0123456789")
    return prefix, int(ref[len(prefix) :] or 0)


# --- canonical JSON & hashes ----------------------------------------------------------------------------


def _default(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return decimal_text(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def decimal_text(value: Decimal) -> str:
    """142.0000 -> '142', 3.5000 -> '3.5', 100 -> '100' (never scientific notation)."""
    return format(value.normalize(), "f")


def canonical_json(obj: Any) -> str:
    """Stable serialisation: sorted keys, no whitespace, UTF-8 kept as-is."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default
    )


def jsonable(obj: Any) -> Any:
    """Round-trip through canonical JSON so what we hash is exactly what Postgres stores."""
    return json.loads(canonical_json(obj))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(manifest))
