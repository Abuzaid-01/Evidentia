"""Hybrid ranking: Reciprocal Rank Fusion over independent retrievers, then an evidence-quality
adjustment. Every contribution is kept so the UI can answer "why this result?"."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evidentia_core.domain.video import span_label

# How much each retriever's ranking counts. All start equal; tune with logged clicks/verifications.
RETRIEVER_WEIGHTS: dict[str, float] = {
    "structured": 1.0,  # filters only (always present); orders by recency
    "lexical": 1.0,  # Postgres full-text over captions/observations/OCR
    "text_vector": 1.0,  # SigLIP text embedding of the search document
    "visual": 1.0,  # SigLIP text->image
    "cloudinary": 0.7,  # Cloudinary Search API (tags/context mirror of our data)
    "activity": 1.2,  # asset has a matching activity observation (verified counts more)
    "segments": 1.15,  # a video time-span whose description matches the query
}


@dataclass
class Hit:
    asset_id: str
    rank: int  # 1-based within its retriever
    score: float | None = None  # raw retriever score (similarity, ts_rank...)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fused:
    asset_id: str
    score: float
    contributions: dict[str, dict[str, Any]] = field(default_factory=dict)
    adjustments: dict[str, float] = field(default_factory=dict)


def reciprocal_rank_fusion(
    results: dict[str, list[Hit]], *, k: int = 60, weights: dict[str, float] | None = None
) -> dict[str, Fused]:
    weights = weights or RETRIEVER_WEIGHTS
    fused: dict[str, Fused] = {}
    for retriever, hits in results.items():
        w = weights.get(retriever, 1.0)
        for hit in hits:
            entry = fused.setdefault(hit.asset_id, Fused(hit.asset_id, 0.0))
            contribution = w / (k + hit.rank)
            entry.score += contribution
            entry.contributions[retriever] = {
                "rank": hit.rank,
                "score": None if hit.score is None else round(float(hit.score), 4),
                "contribution": round(contribution, 5),
                **hit.detail,
            }
    return fused


@dataclass(frozen=True)
class QualitySignals:
    verified_activity_match: bool
    review_required: bool
    exact_duplicate: bool
    quality_score: float | None


def quality_multiplier(signals: QualitySignals) -> dict[str, float]:
    """Multiplicative adjustments (explainable, bounded): verified evidence first, duplicates last."""
    adj: dict[str, float] = {}
    if signals.verified_activity_match:
        adj["verified"] = 1.25
    if signals.review_required:
        adj["unreviewed_issues"] = 0.9
    if signals.exact_duplicate:
        adj["duplicate"] = 0.5
    if signals.quality_score is not None and signals.quality_score < 0.3:
        adj["low_quality"] = 0.85
    return adj


def coverage_multiplier(missing: int, total: int) -> dict[str, float]:
    """Down-rank results that lack some of the query's words: 0.5x when none is covered."""
    if not total or not missing:
        return {}
    return {"partial_match": 0.5 + 0.5 * (total - missing) / total}


def apply_adjustments(entry: Fused, adjustments: dict[str, float]) -> None:
    entry.adjustments = adjustments
    for factor in adjustments.values():
        entry.score *= factor


def explain(entry: Fused) -> list[str]:
    """Short human-readable reasons, strongest first."""
    labels = {
        "activity": "activity match",
        "lexical": "text match",
        "text_vector": "semantic match",
        "visual": "visual match",
        "cloudinary": "Cloudinary search match",
        "structured": "matches filters",
    }
    ordered = sorted(entry.contributions.items(), key=lambda kv: -kv[1]["contribution"])
    reasons = []
    segment = entry.contributions.get("segments") or {}
    if segment.get("start_ms") is not None and segment.get("end_ms") is not None:
        reasons.append(span_label(int(segment["start_ms"]), int(segment["end_ms"])))
    for name, c in ordered:
        if name == "segments":
            continue
        label = labels.get(name, name)
        if name == "activity" and c.get("verified"):
            label = "verified activity match"
        if name == "lexical" and c.get("match") == "some_terms":
            label = "partial text match"
        if c.get("score") is not None and name in {"visual", "text_vector"}:
            label += f" ({c['score']:.2f})"
        reasons.append(label)
    for name in entry.adjustments:
        reasons.append(
            {
                "verified": "human-verified evidence",
                "duplicate": "duplicate (down-ranked)",
                "partial_match": "partial match (down-ranked)",
            }.get(name, name.replace("_", " "))
        )
    return reasons
