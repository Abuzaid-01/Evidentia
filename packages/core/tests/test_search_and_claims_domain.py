from datetime import date
from decimal import Decimal

from evidentia_core.domain.claims import (
    EvidenceFact,
    MetricFact,
    can_move,
    check_rules,
    numbers_in,
    support_level,
)
from evidentia_core.domain.enums import ClaimStatus, ClaimType, SupportLevel, ValidationVerdict
from evidentia_core.domain.ranking import (
    Hit,
    QualitySignals,
    apply_adjustments,
    explain,
    quality_multiplier,
    reciprocal_rank_fusion,
)
from evidentia_core.domain.search_doc import ObservationText, build_search_text
from evidentia_core.domain.search_plan import (
    ActivityRef,
    SearchPlan,
    SiteRef,
    parse_query,
    validate_plan,
)

SITES = [SiteRef("s-a", "A", "Village A"), SiteRef("s-b", "B", "Rampura")]
ACTS = [
    ActivityRef("pipe_installation", "Pipe installation"),
    ActivityRef("tank_construction", "Tank / structure construction"),
]


def parse(q: str) -> SearchPlan:
    return parse_query(q, sites=SITES, activities=ACTS, default_year=2026)


# --- query parsing ---------------------------------------------------------------------------------


def test_parses_site_month_activity() -> None:
    plan = parse("Show pipe installation at Site A in August")
    f = plan.filters
    assert f.site_ids == ["s-a"]
    assert (f.date_from, f.date_to) == (date(2026, 8, 1), date(2026, 8, 31))
    assert f.activities == ["pipe_installation"]
    assert "Pipe installation" in plan.semantic_text


def test_after_before_between() -> None:
    assert parse("tank after July").filters.date_from == date(2026, 8, 1)
    assert parse("tank since July").filters.date_from == date(2026, 7, 1)
    assert parse("before March 2026").filters.date_to == date(2026, 2, 28)
    f = parse("between April and June").filters
    assert (f.date_from, f.date_to) == (date(2026, 4, 1), date(2026, 6, 30))


def test_site_by_name_media_and_flags() -> None:
    f = parse("verified videos from Rampura with workers").filters
    assert f.site_ids == ["s-b"]
    assert f.media_type == "video"
    assert f.verified_only is True
    assert f.people_present is True


def test_unknown_site_is_warned_not_guessed() -> None:
    plan = parse("photos at site Z")
    assert plan.filters.site_ids == []
    assert any("Unknown site" in w for w in plan.warnings)


def test_validate_plan_drops_invented_values() -> None:
    plan = SearchPlan()
    plan.filters.site_ids = ["s-a", "made-up"]
    plan.filters.activities = ["pipe_installation", "rocket_launch"]
    plan.filters.date_from, plan.filters.date_to = date(2026, 9, 1), date(2026, 8, 1)
    out = validate_plan(plan, sites=SITES, activities=ACTS)
    assert out.filters.site_ids == ["s-a"]
    assert out.filters.activities == ["pipe_installation"]
    assert out.filters.date_from < out.filters.date_to
    assert len(out.warnings) == 3


# --- ranking ---------------------------------------------------------------------------------------


def test_rrf_rewards_agreement_across_retrievers() -> None:
    fused = reciprocal_rank_fusion(
        {
            "lexical": [Hit("a", 1), Hit("b", 2)],
            "visual": [Hit("b", 1, 0.2), Hit("c", 2, 0.1)],
        },
        k=60,
    )
    assert fused["b"].score > fused["a"].score > fused["c"].score
    assert set(fused["b"].contributions) == {"lexical", "visual"}


def test_quality_adjustments_and_explanations() -> None:
    fused = reciprocal_rank_fusion({"activity": [Hit("a", 1, 0.9, {"verified": True})]})
    entry = fused["a"]
    before = entry.score
    apply_adjustments(entry, quality_multiplier(QualitySignals(True, False, True, None)))
    assert entry.score == before * 1.25 * 0.5
    reasons = explain(entry)
    assert reasons[0] == "verified activity match"
    assert "duplicate (down-ranked)" in reasons


# --- search document ----------------------------------------------------------------------------------


def test_search_document_excludes_rejected_and_uses_labels() -> None:
    text = build_search_text(
        caption="Workers lower a blue pipe into a trench.",
        observations=[
            ObservationText("activity", "pipe_installation", "depicted", "verified", None, 0.9),
            ObservationText("object", "water_tank", "visible", "rejected", None, 0.5),
            ObservationText(
                "document_text", "visible_text", "extracted", "proposed", {"text": "JALSEVA"}, None
            ),
            ObservationText(
                "scene",
                "image",
                "caption",
                "proposed",
                {"text": "Workers lower a blue pipe into a trench."},
                None,
            ),
        ],
        activity_labels={"pipe_installation": "Pipe installation"},
        site_name="Village A",
        filename="IMG_1.JPG",
        note=None,
    )
    assert "Pipe installation" in text and "JALSEVA" in text and "Village A" in text
    assert "water tank" not in text
    assert text.count("Workers lower a blue pipe") == 1


# --- claim rules -------------------------------------------------------------------------------------------

VERIFIED = EvidenceFact("supports", True)
UNVERIFIED = EvidenceFact("supports", False)


def test_numbers_ignore_years() -> None:
    assert numbers_in("142 households connected in 2026, 1,200 metres, 3.5 km") == [
        "142",
        "1,200",
        "3.5",
    ]


def test_descriptive_needs_verified_support() -> None:
    assert not check_rules(ClaimType.DESCRIPTIVE, "Tank built at Site B", [UNVERIFIED], []).passed
    assert check_rules(ClaimType.DESCRIPTIVE, "Tank built at Site B", [VERIFIED], []).passed


def test_outcome_needs_metric_and_evidence_and_numbers_must_be_sourced() -> None:
    statement = "142 households now have piped water"
    no_metric = check_rules(ClaimType.OUTCOME, statement, [VERIFIED], [])
    assert not no_metric.passed and no_metric.unsourced_numbers == ["142"]
    wrong = check_rules(
        ClaimType.OUTCOME, statement, [VERIFIED], [MetricFact(Decimal("140"), True)]
    )
    assert not wrong.passed
    ok = check_rules(
        ClaimType.OUTCOME, statement, [VERIFIED], [MetricFact(Decimal("142.0000"), True)]
    )
    assert ok.passed


def test_contradictions_block() -> None:
    check = check_rules(
        ClaimType.PROGRESS, "Tank completed", [VERIFIED, EvidenceFact("contradicts", True)], []
    )
    assert not check.passed and check.contradictions == 1


def test_support_levels_and_workflow() -> None:
    ok = check_rules(ClaimType.DESCRIPTIVE, "Tank exists", [VERIFIED], [])
    assert support_level(ClaimStatus.DRAFT, ok, None) == SupportLevel.PROPOSED
    assert (
        support_level(ClaimStatus.IN_REVIEW, ok, ValidationVerdict.SUPPORTED)
        == SupportLevel.REVIEWED
    )
    assert (
        support_level(ClaimStatus.APPROVED, ok, ValidationVerdict.SUPPORTED)
        == SupportLevel.VERIFIED
    )
    assert can_move(ClaimStatus.DRAFT, ClaimStatus.IN_REVIEW)
    assert not can_move(ClaimStatus.APPROVED, ClaimStatus.DRAFT)
    assert not can_move(ClaimStatus.DRAFT, ClaimStatus.APPROVED)
