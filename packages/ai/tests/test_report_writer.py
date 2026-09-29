from __future__ import annotations

from evidentia_ai.providers.base import ProviderRetryableError
from evidentia_ai.report_writer import ClaimBrief, MetricBrief, fallback_narrative, write_narrative
from evidentia_ai.text_llm import JsonAnswer, MockText

CLAIMS = [
    ClaimBrief(
        "C1", "outcome", "142 households now collect piped water", "Village A", None, ["M1"]
    ),
    ClaimBrief("C2", "descriptive", "Pipes were laid in an open trench.", "Village A", None),
]
METRICS = [MetricBrief("M1", "Households connected", "142", "households", "field_survey: HH-7")]


def _write(llms: list) -> tuple[dict, dict]:  # type: ignore[type-arg]
    draft = write_narrative(
        project="Water", period=None, audience="internal", claims=CLAIMS, metrics=METRICS, llms=llms
    )
    return draft.sections, draft.meta


def test_fallback_states_claims_verbatim_with_self_citations() -> None:
    narrative = fallback_narrative(CLAIMS)
    assert narrative["summary"] == [
        {"text": "142 households now collect piped water.", "cites": ["C1"]}
    ]
    assert narrative["overview"] == [
        {"text": "Pipes were laid in an open trench.", "cites": ["C2"]}
    ]


def test_no_llm_uses_fallback() -> None:
    sections, meta = _write([])
    assert meta["mode"] == "fallback" and sections["summary"][0]["cites"] == ["C1"]


def test_llm_answer_is_passed_through_with_provenance() -> None:
    answer = {
        "summary": [{"text": "142 households now collect piped water.", "cites": ["C1", "M1"]}],
        "overview": [{"text": "Pipes were laid at Village A.", "cites": ["C2"]}],
    }
    sections, meta = _write([MockText(answer)])
    assert sections == answer
    assert meta["mode"] == "llm" and meta["model"] == "mock-text-1" and meta["prompt_hash"]


def test_invalid_or_failing_llm_falls_back() -> None:
    _, meta = _write([MockText({"summary": "not a list"})])
    assert meta["mode"] == "fallback" and meta["reason"] == "invalid LLM answer"

    class Down(MockText):
        def complete_json(self, system: str, user: str) -> JsonAnswer:
            raise ProviderRetryableError("503")

    _, meta = _write([Down()])
    assert meta["mode"] == "fallback" and meta["errors"]
