from __future__ import annotations

from datetime import date
from decimal import Decimal

from evidentia_core.domain.enums import CitationKind
from evidentia_core.domain.reports import (
    Citation,
    CitationContext,
    canonical_json,
    check_narrative,
    decimal_text,
    derive_limitations,
    jsonable,
    manifest_hash,
    normalize_narrative,
    periods_overlap,
    sentence_problems,
    split_sentences,
)

CTX = CitationContext(
    claim_metrics={"c-outcome": frozenset({"m-142"}), "c-pipes": frozenset()},
    metric_values={"m-142": Decimal("142.0000"), "m-3.5": Decimal("3.5")},
)
CLAIM = Citation(CitationKind.CLAIM, "c-outcome")
PIPES = Citation(CitationKind.CLAIM, "c-pipes")


def test_sentence_needs_a_known_citation() -> None:
    assert sentence_problems("Pipes were laid.", [], CTX) == ["Sentence has no citation"]
    assert (
        "not in this report"
        in sentence_problems("Pipes were laid.", [Citation(CitationKind.CLAIM, "other")], CTX)[0]
    )
    assert sentence_problems("Pipes were laid at Village A.", [PIPES], CTX) == []


def test_numbers_must_match_cited_metrics() -> None:
    # a claim's linked metric counts; years are context, not quantities
    assert sentence_problems("In 2026, 142 households were connected.", [CLAIM], CTX) == []
    assert sentence_problems("About 150 households were connected.", [CLAIM], CTX) == [
        "Number '150' does not match any cited metric"
    ]
    # a number from a metric that is not cited is still unsourced
    assert sentence_problems("Tanks hold 3.5 megalitres.", [PIPES], CTX)
    assert (
        sentence_problems(
            "Tanks hold 3.5 megalitres.", [Citation(CitationKind.METRIC, "m-3.5")], CTX
        )
        == []
    )


def test_normalize_splits_sentences_and_keeps_citations() -> None:
    narrative = normalize_narrative(
        {
            "summary": [
                {
                    "text": "Pipes were laid. 142 households were connected!",
                    "cites": [{"type": "claim", "id": "c-outcome"}] * 2,
                }
            ]
        }
    )
    assert [s["text"] for s in narrative["summary"]] == [
        "Pipes were laid.",
        "142 households were connected!",
    ]
    assert all(s["cites"] == [{"type": "claim", "id": "c-outcome"}] for s in narrative["summary"])
    assert narrative["overview"] == []
    assert check_narrative(narrative, CTX) == []


def test_check_narrative_reports_position() -> None:
    problems = check_narrative(
        {"summary": [], "overview": [{"text": "Uncited.", "cites": []}]}, CTX
    )
    assert [(p.section, p.index) for p in problems] == [("overview", 0)]


def test_split_sentences_keeps_decimals_together() -> None:
    assert split_sentences("Flow rose to 3.5 litres. Work continues.") == [
        "Flow rose to 3.5 litres.",
        "Work continues.",
    ]


def test_periods_overlap_with_open_ends() -> None:
    aug, sep = date(2026, 8, 1), date(2026, 9, 30)
    assert periods_overlap(aug, sep, None, None)
    assert periods_overlap(aug, sep, date(2026, 9, 1), None)
    assert not periods_overlap(aug, sep, date(2026, 10, 1), None)
    assert not periods_overlap(aug, sep, None, date(2026, 7, 31))


def test_limitations_are_cited_and_digit_free() -> None:
    manifest = {
        "claims": [
            {
                "ref": "C1",
                "id": "a",
                "claim_type": "outcome",
                "validation": {"verdict": "supported"},
            },
            {"ref": "C2", "id": "b", "claim_type": "progress", "validation": None},
        ],
        "metrics": [{"ref": "M1", "id": "m", "source_type": "visual_count"}],
        "evidence": [{"ref": "E1", "claim_ref": "C2", "asset_ref": "A1"}],
        "assets": [{"ref": "A1", "capture_time_source": "upload"}],
    }
    limitations = derive_limitations(manifest)
    assert len(limitations) == 4  # visual claim, no validator, weak timestamp, visual-count metric
    for item in limitations:
        assert item["cites"] and not any(ch.isdigit() for ch in item["text"])
    assert {"type": "metric", "id": "m"} in limitations[-1]["cites"]


def test_canonical_json_and_hash_are_stable() -> None:
    a = {"b": [1, 2], "a": {"d": date(2026, 9, 1), "v": Decimal("142.0000")}}
    b = {"a": {"v": Decimal("142"), "d": date(2026, 9, 1)}, "b": [1, 2]}
    assert canonical_json(a) == canonical_json(b)
    assert manifest_hash(jsonable(a)) == manifest_hash(a)
    assert decimal_text(Decimal("100.0000")) == "100"
    assert decimal_text(Decimal("3.5000")) == "3.5"
