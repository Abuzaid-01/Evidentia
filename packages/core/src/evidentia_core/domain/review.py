"""Review-priority scoring.

Weights follow the blueprint's starting heuristic. They are an engineering prior, not a scientific
standard, and will be calibrated on reviewer decisions later. Higher = review sooner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WEIGHTS = {
    "model_uncertainty": 0.30,
    "metadata_uncertainty": 0.20,
    "geo_time_inconsistency": 0.20,
    "lack_of_corroboration": 0.20,
    "claim_criticality": 0.10,
}


@dataclass(frozen=True)
class ReviewSignals:
    model_uncertainty: float  # 1 - confidence (0.5 when the model gives no confidence)
    metadata_uncertainty: float  # 0 = trusted capture time + GPS, 1 = neither
    geo_time_inconsistency: float  # 1 when GPS is outside the site or date outside the project
    lack_of_corroboration: float  # 1 when no second source agrees
    claim_criticality: float = 0.0  # populated once claims exist (Phase 4)

    def score(self) -> float:
        raw = sum(WEIGHTS[name] * _clamp(getattr(self, name)) for name in WEIGHTS)
        return round(raw, 4)

    def explain(self) -> dict[str, float]:
        return {name: round(WEIGHTS[name] * _clamp(getattr(self, name)), 4) for name in WEIGHTS}


@dataclass
class AssetReviewDecision:
    needs_review: bool
    priority: float
    reasons: list[str] = field(default_factory=list)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def metadata_uncertainty(capture_source: str | None, location_source: str | None) -> float:
    trusted = {"exif", "device"}
    score = 0.0
    if capture_source not in trusted:
        score += 0.5
    if location_source not in trusted:
        score += 0.5
    return score


def model_uncertainty(confidence: float | None) -> float:
    if confidence is None:
        return 0.5
    return 1.0 - _clamp(confidence)
