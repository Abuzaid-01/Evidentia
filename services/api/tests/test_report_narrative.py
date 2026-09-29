"""The gate between model output and the stored narrative (no database needed)."""

from __future__ import annotations

from decimal import Decimal

from evidentia_api.services.reports import _resolve_refs
from evidentia_core.domain.reports import CitationContext

CTX = CitationContext(
    claim_metrics={"claim-1": frozenset({"metric-1"}), "claim-2": frozenset()},
    metric_values={"metric-1": Decimal("142")},
)
REFMAP = {
    "C1": {"type": "claim", "id": "claim-1"},
    "C2": {"type": "claim", "id": "claim-2"},
    "M1": {"type": "metric", "id": "metric-1"},
}


def test_model_sentences_are_mapped_checked_and_filtered() -> None:
    model_output = {
        "summary": [
            # good: number backed by the claim's metric; inline markers become citations
            {"text": "142 households now collect piped water [C1].", "cites": []},
            # hallucinated number
            {"text": "Water use rose by 40%.", "cites": ["C1"]},
            # unknown reference
            {"text": "A school was connected.", "cites": ["C9"]},
        ],
        "overview": [
            {"text": "Pipes were laid at Village A. Work finished in August.", "cites": ["C2"]},
            {"text": "Nobody cites this.", "cites": []},
        ],
    }
    narrative, rejected = _resolve_refs(model_output, REFMAP, CTX)
    assert narrative["summary"] == [
        {
            "text": "142 households now collect piped water.",
            "cites": [{"type": "claim", "id": "claim-1"}],
        }
    ]
    assert [s["text"] for s in narrative["overview"]] == [
        "Pipes were laid at Village A.",
        "Work finished in August.",
    ]
    reasons = {r["text"]: r["problems"] for r in rejected}
    assert reasons["Water use rose by 40%."] == ["Number '40' does not match any cited metric"]
    assert "Unknown reference C9" in reasons["A school was connected."]
    assert reasons["Nobody cites this."] == ["Sentence has no citation"]
