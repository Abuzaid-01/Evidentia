"""Structured search plans and the deterministic query parser.

A natural-language query becomes a `SearchPlan`: hard filters (site, dates, media type, activities,
verification) plus free text for semantic/visual retrieval. The deterministic parser always runs; an
LLM planner (evidentia_ai.planner) may refine it, but its output is validated against the tenant's
real sites and taxonomy. Unknown values are dropped with a warning, never guessed.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from pydantic import BaseModel, Field

MediaType = str  # "image" | "video"


class SearchFilters(BaseModel):
    site_ids: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None  # inclusive
    media_type: str | None = Field(default=None, pattern="^(image|video)$")
    verified_only: bool = False
    needs_review: bool | None = None
    people_present: bool | None = None


class SearchPlan(BaseModel):
    filters: SearchFilters = Field(default_factory=SearchFilters)
    semantic_text: str = ""  # lexical + text-vector retrieval
    visual_text: str = ""  # text->image retrieval (describes what should be *visible*)
    planner: str = "rules"  # rules | rules+<llm provider>
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class SiteRef:
    id: str
    code: str
    name: str


@dataclass(frozen=True)
class ActivityRef:
    key: str
    label: str


_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS |= {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR = r"(?:\s+(?P<{n}>20\d\d))?"

_BETWEEN = re.compile(
    rf"\bbetween\s+(?P<m1>{_MONTH_RE}){_YEAR.format(n='y1')}\s+(?:and|to|-)\s+(?P<m2>{_MONTH_RE}){_YEAR.format(n='y2')}\b",
    re.I,
)
_AFTER = re.compile(rf"\b(?:after|since|from)\s+(?P<m>{_MONTH_RE}){_YEAR.format(n='y')}\b", re.I)
_BEFORE = re.compile(
    rf"\b(?:before|until|till|up to)\s+(?P<m>{_MONTH_RE}){_YEAR.format(n='y')}\b", re.I
)
_IN = re.compile(rf"\b(?:in|during|of)?\s*(?P<m>{_MONTH_RE}){_YEAR.format(n='y')}\b", re.I)
_SITE = re.compile(r"\bsite\s+(?P<code>[A-Za-z0-9_-]{1,40})\b", re.I)
_VIDEO = re.compile(r"\b(videos?|clips?|footage)\b", re.I)
_IMAGE = re.compile(r"\b(photos?|images?|pictures?|pics?)\b", re.I)
_VERIFIED = re.compile(r"\b(verified|approved|confirmed)\b", re.I)
_REVIEW = re.compile(r"\b(needs? review|unreviewed|to review|uncertain)\b", re.I)
_PEOPLE = re.compile(
    r"\b(people|workers?|villagers?|community members?|children|women|men)\b", re.I
)
_FILLER = re.compile(
    r"\b(show( me)?|find|search( for)?|get|list|all|any|the|of|at|in|on|for|with|during|evidence|media|please|where|that|which)\b",
    re.I,
)


def _year(value: str | None, default: int) -> int:
    return int(value) if value else default


def _month_range(month: int, year: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def parse_query(
    query: str,
    *,
    sites: list[SiteRef],
    activities: list[ActivityRef],
    default_year: int,
) -> SearchPlan:
    """Deterministic, explainable parsing. Recognised phrases are removed from the free text."""
    text = query.strip()
    plan = SearchPlan()
    f = plan.filters
    consumed: list[tuple[int, int]] = []

    def take(match: re.Match[str]) -> None:
        consumed.append(match.span())

    # --- dates -----------------------------------------------------------------------------------
    if m := _BETWEEN.search(text):
        y1 = _year(m["y1"], _year(m["y2"], default_year))
        y2 = _year(m["y2"], y1)
        f.date_from = _month_range(_MONTHS[m["m1"].lower()], y1)[0]
        f.date_to = _month_range(_MONTHS[m["m2"].lower()], y2)[1]
        take(m)
    else:
        if m := _AFTER.search(text):
            month, year = _MONTHS[m["m"].lower()], _year(m["y"], default_year)
            if m.group(0).lower().startswith("after"):  # "after July" excludes July
                f.date_from = _month_range(month, year)[1] + timedelta(days=1)
            else:  # "since/from July" includes it
                f.date_from = _month_range(month, year)[0]
            take(m)
        if m := _BEFORE.search(text):
            month, year = _MONTHS[m["m"].lower()], _year(m["y"], default_year)
            f.date_to = _month_range(month, year)[0] - timedelta(days=1)
            take(m)
        if f.date_from is None and f.date_to is None and (m := _IN.search(text)):
            month, year = _MONTHS[m["m"].lower()], _year(m["y"], default_year)
            f.date_from, f.date_to = _month_range(month, year)
            take(m)

    # --- sites (by code "site A" or by full name) ----------------------------------------------------
    by_code = {s.code.lower(): s for s in sites}
    for m in _SITE.finditer(text):
        site = by_code.get(m["code"].lower())
        if site:
            f.site_ids.append(site.id)
            take(m)
        else:
            plan.warnings.append(f"Unknown site '{m['code']}' ignored")
    lowered = text.lower()
    for site in sites:
        idx = lowered.find(site.name.lower())
        if site.name and idx >= 0 and site.id not in f.site_ids:
            f.site_ids.append(site.id)
            consumed.append((idx, idx + len(site.name)))

    # --- activities (key, label, or label words) ---------------------------------------------------
    for activity in activities:
        for phrase in {activity.key.replace("_", " "), activity.label.lower()}:
            idx = lowered.find(phrase.lower())
            if idx >= 0 and activity.key not in f.activities:
                f.activities.append(activity.key)
                consumed.append((idx, idx + len(phrase)))
                break

    # --- flags ------------------------------------------------------------------------------------------
    if m := _VIDEO.search(text):
        f.media_type = "video"
        take(m)
    elif m := _IMAGE.search(text):
        f.media_type = "image"
        take(m)
    if m := _VERIFIED.search(text):
        f.verified_only = True
        take(m)
    if m := _REVIEW.search(text):
        f.needs_review = True
        take(m)

    # --- remaining free text -------------------------------------------------------------------------
    keep = [ch if not any(a <= i < b for a, b in consumed) else " " for i, ch in enumerate(text)]
    free = _FILLER.sub(" ", "".join(keep))
    free = re.sub(r"[^\w\s'-]", " ", free)
    free = re.sub(r"\s+", " ", free).strip()
    # Activities stay in the free text as well: they help lexical and visual ranking.
    activity_words = " ".join(a.label for a in activities if a.key in f.activities)
    plan.semantic_text = " ".join(x for x in (free, activity_words) if x).strip()
    plan.visual_text = plan.semantic_text
    if _PEOPLE.search(free):
        f.people_present = True
    return plan


def validate_plan(
    plan: SearchPlan, *, sites: list[SiteRef], activities: list[ActivityRef]
) -> SearchPlan:
    """Drop anything that does not exist in this tenant/project (LLM output is untrusted)."""
    valid_sites = {s.id for s in sites}
    valid_acts = {a.key for a in activities}
    f = plan.filters
    for sid in [s for s in f.site_ids if s not in valid_sites]:
        plan.warnings.append(f"Ignored unknown site id {sid}")
    for act in [a for a in f.activities if a not in valid_acts]:
        plan.warnings.append(f"Ignored unknown activity '{act}'")
    f.site_ids = list(dict.fromkeys(s for s in f.site_ids if s in valid_sites))
    f.activities = list(dict.fromkeys(a for a in f.activities if a in valid_acts))
    if f.date_from and f.date_to and f.date_from > f.date_to:
        plan.warnings.append("Date range was inverted; swapped")
        f.date_from, f.date_to = f.date_to, f.date_from
    plan.semantic_text = plan.semantic_text[:500]
    plan.visual_text = plan.visual_text[:300]
    return plan
