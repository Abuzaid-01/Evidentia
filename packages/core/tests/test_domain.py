from itertools import pairwise

import pytest
from evidentia_core.domain import review
from evidentia_core.domain.enums import AssetState as S
from evidentia_core.domain.enums import ResourceType, Role
from evidentia_core.domain.geo import haversine_m, valid_coordinates
from evidentia_core.domain.media_policy import (
    MediaLimits,
    MediaRejected,
    check_declared,
    check_stored,
)
from evidentia_core.domain.state_machine import InvalidTransition, assert_transition, can_transition
from evidentia_core.domain.taxonomy import PRESETS, Activity, TaxonomySpec, preset

LIMITS = MediaLimits(max_image_bytes=100, max_video_bytes=1000, max_video_seconds=60)


# --- state machine -------------------------------------------------------------------------------


def test_happy_path_is_allowed() -> None:
    path = [
        S.AWAITING_UPLOAD,
        S.UPLOADED,
        S.REGISTERED,
        S.METADATA_READY,
        S.DEDUP_CHECKED,
        S.ANALYZING,
        S.INDEXED,
        S.READY,
    ]
    for current, target in pairwise(path):
        assert_transition(current, target)


def test_cannot_skip_steps_or_go_backwards() -> None:
    assert not can_transition(S.UPLOADED, S.ANALYZING)
    assert not can_transition(S.INDEXED, S.REGISTERED)
    with pytest.raises(InvalidTransition):
        assert_transition(S.AWAITING_UPLOAD, S.READY)


def test_failures_only_from_in_flight_states() -> None:
    assert can_transition(S.ANALYZING, S.FAILED_RETRYABLE)
    assert can_transition(S.FAILED_RETRYABLE, S.FAILED_RETRYABLE)
    assert can_transition(S.AWAITING_UPLOAD, S.FAILED_PERMANENT)
    assert not can_transition(S.READY, S.FAILED_RETRYABLE)
    assert not can_transition(S.EXPIRED, S.FAILED_PERMANENT)


def test_retry_resumes_and_reanalysis_restarts_enrichment() -> None:
    assert can_transition(S.FAILED_RETRYABLE, S.METADATA_READY)
    assert can_transition(S.READY, S.DEDUP_CHECKED)
    assert can_transition(S.FAILED_PERMANENT, S.DEDUP_CHECKED)


# --- roles -----------------------------------------------------------------------------------------


def test_role_hierarchy() -> None:
    assert Role.ADMIN.at_least(Role.MANAGER)
    assert Role.REVIEWER.at_least(Role.CONTRIBUTOR)
    assert not Role.VIEWER.at_least(Role.CONTRIBUTOR)


# --- media policy -------------------------------------------------------------------------------------


def test_declared_media_checks() -> None:
    assert check_declared("image/jpeg", 50, LIMITS) == ResourceType.IMAGE
    assert check_declared("VIDEO/MP4", 500, LIMITS) == ResourceType.VIDEO
    with pytest.raises(MediaRejected):
        check_declared("application/pdf", 10, LIMITS)
    with pytest.raises(MediaRejected):
        check_declared("image/png", 101, LIMITS)
    with pytest.raises(MediaRejected):
        check_declared("image/png", 0, LIMITS)


def test_stored_media_is_revalidated() -> None:
    check_stored(ResourceType.VIDEO, "mp4", 500, 30.0, LIMITS)
    with pytest.raises(MediaRejected):
        check_stored(ResourceType.VIDEO, "mp4", 500, 61.0, LIMITS)
    with pytest.raises(MediaRejected):
        check_stored(ResourceType.IMAGE, "gif", 10, None, LIMITS)


# --- taxonomy --------------------------------------------------------------------------------------------


def test_presets_are_valid_and_fit_ai_vision_limits() -> None:
    for name, spec in PRESETS.items():
        assert spec.activities, name
        assert len(spec.keys()) == len(set(spec.keys()))


def test_preset_returns_copy() -> None:
    spec = preset("reforestation")
    spec.activities.pop()
    assert len(preset("reforestation").activities) == len(PRESETS["reforestation"].activities)


def test_taxonomy_rejects_duplicates_and_bad_keys() -> None:
    a = Activity(key="dig", label="Dig", description="d", question="q?")
    with pytest.raises(ValueError):
        TaxonomySpec(activities=[a, a])
    with pytest.raises(ValueError):
        Activity(key="Bad Key", label="x", description="d", question="q?")


# --- review priority -----------------------------------------------------------------------------------


def test_review_priority_orders_risky_evidence_first() -> None:
    risky = review.ReviewSignals(0.6, 1.0, 1.0, 1.0)
    safe = review.ReviewSignals(0.05, 0.0, 0.0, 0.0)
    assert risky.score() > safe.score()
    assert 0 <= safe.score() <= risky.score() <= 1
    assert set(risky.explain()) == set(review.WEIGHTS)


def test_metadata_uncertainty() -> None:
    assert review.metadata_uncertainty("exif", "exif") == 0
    assert review.metadata_uncertainty("user", "exif") == 0.5
    assert review.metadata_uncertainty("upload", "none") == 1.0
    assert review.model_uncertainty(None) == 0.5


# --- geo ----------------------------------------------------------------------------------------------------


def test_geo_helpers() -> None:
    assert haversine_m(28.61, 77.21, 28.61, 77.21) == pytest.approx(0)
    assert haversine_m(28.61, 77.21, 28.62, 77.21) == pytest.approx(1112, rel=0.01)
    assert not valid_coordinates(0.0, 0.0)
    assert not valid_coordinates(None, 10.0)
    assert valid_coordinates(25.7, 71.4)
