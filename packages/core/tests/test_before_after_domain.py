from datetime import UTC, date, datetime

from evidentia_core.domain.before_after import (
    ALWAYS,
    PhotoFacts,
    alignment_grade,
    change_summary,
    default_windows,
    derive_limitations,
    rank_score,
)
from evidentia_core.domain.claims import numbers_in

STRONG = {
    "ok": True,
    "inliers": 300,
    "inlier_ratio": 0.8,
    "overlap": 0.95,
    "rotation_deg": 1,
    "scale": 1.0,
    "perspective": 0.01,
}
WEAK = {
    "ok": True,
    "inliers": 20,
    "inlier_ratio": 0.25,
    "overlap": 0.4,
    "rotation_deg": 25,
    "scale": 1.0,
    "perspective": 0.0,
}
FAILED = {"ok": False, "inliers": 3, "inlier_ratio": 0.1, "overlap": 0.0}
CHANGE = {
    "changed_share": 0.35,
    "green_cover_before": 0.1,
    "green_cover_after": 0.3,
    "luminance_shift": 40.0,
}


def facts(
    when: datetime | None, source: str = "exif", gps: bool = True, size: int = 1600
) -> PhotoFacts:
    return PhotoFacts(when, source, gps, size, size, 0.8)


def test_geometry_decides_the_ranking() -> None:
    assert alignment_grade(STRONG) == "strong" and alignment_grade(WEAK) == "partial"
    assert alignment_grade(FAILED) == "none" and alignment_grade(None) == "none"
    # a very similar-looking photo that fails geometric verification loses to a verified one
    assert rank_score(0.99, FAILED) < rank_score(0.6, WEAK) < rank_score(0.6, STRONG)
    # before analysis, similarity alone orders candidates
    assert rank_score(0.9, None) > rank_score(0.8, None)
    # without embeddings, geometry alone
    assert rank_score(None, STRONG) > rank_score(None, WEAK) > rank_score(None, FAILED) == 0


def test_change_summary_is_worded_without_numbers() -> None:
    text = change_summary(CHANGE, STRONG)
    assert text == "Visible change across a large part of the shared view; green cover increased."
    assert "not measured" in change_summary(None, FAILED)
    assert numbers_in(text) == []


def test_limitations_cover_alignment_lighting_season_and_provenance() -> None:
    before = facts(datetime(2026, 2, 1, tzinfo=UTC), source="upload", gps=False, size=480)
    after = facts(datetime(2026, 8, 20, tzinfo=UTC))
    lims = derive_limitations(WEAK, CHANGE, before, after, None)
    joined = " ".join(lims)
    assert lims[0] == ALWAYS
    for phrase in (
        "few matching features",
        "overlap only partly",
        "parallax",
        "Lighting differs",
        "Excess Green",
        "different seasons",
        "upload time",
        "no GPS",
        "low resolution",
    ):
        assert phrase in joined, phrase
    assert all(numbers_in(sentence) == [] for sentence in lims)  # safe to show in reports


def test_clean_pair_keeps_only_the_essential_limitations() -> None:
    before, after = (
        facts(datetime(2026, 8, 1, tzinfo=UTC)),
        facts(datetime(2026, 8, 30, tzinfo=UTC)),
    )
    lims = derive_limitations(STRONG, {**CHANGE, "luminance_shift": 3}, before, after, 12.0)
    assert lims == [ALWAYS, lims[1]] and "Excess Green" in lims[1]
    failed = derive_limitations(FAILED, None, before, after, 12.0)
    assert any("could not be aligned" in s for s in failed)
    reversed_dates = derive_limitations(STRONG, None, after, before, 12.0)
    assert any("not dated later" in s for s in reversed_dates)


def test_default_windows_split_the_date_range() -> None:
    w = default_windows([date(2026, 7, 1), date(2026, 7, 10), date(2026, 9, 28)])
    assert (
        w is not None and w.baseline_from == date(2026, 7, 1) and w.endline_to == date(2026, 9, 28)
    )
    assert (
        w.baseline_to is not None and w.endline_from is not None and w.baseline_to < w.endline_from
    )
    assert default_windows([date(2026, 7, 1), date(2026, 7, 3)]) is None
    assert default_windows([date(2026, 7, 1)]) is None
