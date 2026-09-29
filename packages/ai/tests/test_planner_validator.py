from datetime import date

from evidentia_ai.claim_validator import EvidenceItem, MetricItem, validate_claim
from evidentia_ai.planner import plan_query
from evidentia_ai.providers.base import ProviderRetryableError
from evidentia_ai.text_llm import MockText
from evidentia_core.domain.enums import ValidationVerdict
from evidentia_core.domain.search_plan import ActivityRef, SiteRef

SITES = [SiteRef("s-a", "A", "Village A")]
ACTS = [
    ActivityRef("pipe_installation", "Pipe installation"),
    ActivityRef("excavation", "Excavation"),
]
TODAY = date(2026, 9, 25)


class Down:
    name, model = "gemini", "g"

    def complete_json(self, system: str, user: str) -> None:
        raise ProviderRetryableError("429")


def test_planner_rules_only_without_llm() -> None:
    plan = plan_query("pipe installation at site A", sites=SITES, activities=ACTS, today=TODAY)
    assert plan.planner == "rules" and plan.filters.site_ids == ["s-a"]


def test_llm_refines_but_cannot_invent() -> None:
    llm = MockText(
        {
            "site_ids": ["s-a", "s-invented"],
            "activities": ["excavation", "teleportation"],
            "date_from": "2026-08-01",
            "visual_text": "open trench with a yellow excavator",
        }
    )
    plan = plan_query("digging work", sites=SITES, activities=ACTS, today=TODAY, llms=[llm])
    assert plan.planner == "rules+mock"
    assert plan.filters.site_ids == ["s-a"]
    assert plan.filters.activities == ["excavation"]
    assert plan.filters.date_from == date(2026, 8, 1)
    assert plan.visual_text == "open trench with a yellow excavator"
    assert len(plan.warnings) == 2


def test_llm_outage_degrades_to_rules() -> None:
    plan = plan_query("excavation", sites=SITES, activities=ACTS, today=TODAY, llms=[Down()])  # type: ignore[list-item]
    assert plan.filters.activities == ["excavation"]
    assert "rules only" in plan.warnings[-1]


EVIDENCE = [EvidenceItem("e1", "supports", "activity 'tank construction' depicted (verified)")]
METRICS = [MetricItem("m1", "households connected = 142 (field_survey: HH-7)")]


def test_validator_not_checked_without_llm() -> None:
    result = validate_claim("Tank built", "descriptive", EVIDENCE, [], [])
    assert result.verdict == ValidationVerdict.NOT_CHECKED


def test_validator_filters_hallucinated_citations() -> None:
    llm = MockText(
        {
            "verdict": "partially_supported",
            "reasoning": "Structure is visible; usage is not shown.",
            "unsupported_parts": ["now used daily"],
            "cited_evidence_ids": ["e1", "m1", "e99"],
        }
    )
    result = validate_claim("Tank built and used daily", "progress", EVIDENCE, METRICS, [llm])
    assert result.verdict == ValidationVerdict.PARTIALLY_SUPPORTED
    assert result.details["cited_evidence_ids"] == ["e1", "m1"]
    assert result.details["hallucinated_citations"] == ["e99"]


def test_validator_invalid_answer_is_not_trusted() -> None:
    result = validate_claim(
        "x claim", "descriptive", EVIDENCE, [], [MockText({"verdict": "definitely"})]
    )
    assert result.verdict == ValidationVerdict.NOT_CHECKED
