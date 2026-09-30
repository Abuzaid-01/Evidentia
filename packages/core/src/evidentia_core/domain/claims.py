"""Deterministic claim support rules. These run before (and regardless of) any LLM validation.

Rules:
  * descriptive / progress: at least one SUPPORTS link to a VERIFIED observation
  * outcome: at least one sourced metric AND at least one verified supporting observation
  * metric: at least one sourced metric
  * every number in the statement must equal a linked metric value (no invented numbers)
  * contradicting verified evidence blocks approval unless a reviewer overrides with a note
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from evidentia_core.domain.enums import ClaimStatus, ClaimType, SupportLevel, ValidationVerdict


@dataclass(frozen=True)
class EvidenceFact:
    relation: str  # supports | contradicts | context
    observation_verified: (
        bool  # linked observation is VERIFIED (or asset-level link to a verified asset)
    )


@dataclass(frozen=True)
class MetricFact:
    value: Decimal
    has_source: bool


@dataclass
class RuleCheck:
    passed: bool
    problems: list[str] = field(default_factory=list)
    unsourced_numbers: list[str] = field(default_factory=list)
    verified_support: int = 0
    contradictions: int = 0
    sourced_metrics: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "problems": self.problems,
            "unsourced_numbers": self.unsourced_numbers,
            "verified_support": self.verified_support,
            "contradictions": self.contradictions,
            "sourced_metrics": self.sourced_metrics,
        }


# Numbers like 142, 1,200, 3.5, 25% (years and ordinals handled below)
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(%?)(?![\w])")
_YEARISH = re.compile(r"^(19|20)\d\d$")


# A number right after one of these words is a name or an address ("Street 15", "Ward 12",
# "Site no. 3", "Day 2"), not a quantity, so it needs no metric. "15 streets" is still a quantity.
_LABEL_WORDS = frozenset(
    [
        "street",
        "st",
        "road",
        "rd",
        "lane",
        "avenue",
        "ave",
        "ward",
        "sector",
        "block",
        "site",
        "zone",
        "plot",
        "house",
        "building",
        "gate",
        "phase",
        "area",
        "route",
        "village",
        "district",
        "colony",
        "section",
        "unit",
        "day",
        "week",
        "no",
        "number",
    ]
)
_WORD_BEFORE = re.compile(r"([A-Za-z]+)\.?\s*#?\s*$|(#)\s*$")


def numbers_in(statement: str) -> list[str]:
    """Quantities stated in a sentence (years and name/address numbers excluded)."""
    found = []
    for match in _NUMBER.finditer(statement):
        raw = match.group(1)
        if _YEARISH.match(raw):  # dates like 2026 are context, not quantities
            continue
        before = _WORD_BEFORE.search(statement[max(0, match.start() - 20) : match.start()])
        if before and (before.group(2) or before.group(1).lower() in _LABEL_WORDS):
            continue
        found.append(raw)
    return found


def _as_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def check_rules(
    claim_type: ClaimType, statement: str, evidence: list[EvidenceFact], metrics: list[MetricFact]
) -> RuleCheck:
    verified_support = sum(
        1 for e in evidence if e.relation == "supports" and e.observation_verified
    )
    contradictions = sum(
        1 for e in evidence if e.relation == "contradicts" and e.observation_verified
    )
    sourced = [m for m in metrics if m.has_source]
    check = RuleCheck(
        passed=True,
        verified_support=verified_support,
        contradictions=contradictions,
        sourced_metrics=len(sourced),
    )

    needs_evidence = claim_type in {ClaimType.DESCRIPTIVE, ClaimType.PROGRESS, ClaimType.OUTCOME}
    needs_metric = claim_type in {ClaimType.OUTCOME, ClaimType.METRIC}
    if needs_evidence and verified_support == 0:
        check.problems.append("Needs at least one supporting link to a human-verified observation")
    if needs_metric and not sourced:
        check.problems.append(
            f"A {claim_type.value} claim needs at least one metric with a declared source"
        )
    if contradictions:
        check.problems.append(f"{contradictions} verified observation(s) contradict this claim")

    metric_values = {m.value.normalize() for m in sourced}
    for raw in numbers_in(statement):
        value = _as_decimal(raw)
        if value is None or value.normalize() not in metric_values:
            check.unsourced_numbers.append(raw)
    if check.unsourced_numbers:
        check.problems.append(
            "Numbers without a linked sourced metric: " + ", ".join(check.unsourced_numbers)
        )

    check.passed = not check.problems
    return check


def support_level(
    status: ClaimStatus, rules: RuleCheck, verdict: ValidationVerdict | None
) -> SupportLevel:
    if not rules.passed:
        return SupportLevel.UNSUPPORTED
    if status == ClaimStatus.APPROVED:
        return SupportLevel.VERIFIED
    if verdict in {
        ValidationVerdict.SUPPORTED,
        ValidationVerdict.PARTIALLY_SUPPORTED,
        ValidationVerdict.NOT_CHECKED,
    }:
        return SupportLevel.REVIEWED
    return SupportLevel.PROPOSED


# Allowed workflow transitions
CLAIM_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    ClaimStatus.DRAFT: {ClaimStatus.IN_REVIEW, ClaimStatus.RETRACTED},
    ClaimStatus.IN_REVIEW: {ClaimStatus.APPROVED, ClaimStatus.REJECTED, ClaimStatus.DRAFT},
    ClaimStatus.REJECTED: {ClaimStatus.DRAFT, ClaimStatus.RETRACTED},
    ClaimStatus.APPROVED: {
        ClaimStatus.RETRACTED
    },  # approved claims are immutable; retract + supersede
    ClaimStatus.RETRACTED: set(),
}


def can_move(current: ClaimStatus, target: ClaimStatus) -> bool:
    return target in CLAIM_TRANSITIONS[current]
