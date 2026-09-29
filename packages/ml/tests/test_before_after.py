"""Before/after ML on synthetic repeat photography (see evidentia_ml.synthetic): the after photo is
the same scene from a shifted camera under different light, for half the scenes with new
vegetation. Distractors are other scenes."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from evidentia_core.domain.before_after import rank_score
from evidentia_ml.before_after import (
    ImageDecodeError,
    align,
    analyze_pair,
    analyze_pair_bytes,
    pixel_homography,
    prepare,
    prepare_array,
)
from evidentia_ml.synthetic import GREEN_AXES, GREEN_CENTRE, H, W, repeat_photo, scene
from evidentia_ml.synthetic import jpeg as encode


def after_of(img: np.ndarray, seed: int, *, green: bool) -> tuple[np.ndarray, np.ndarray]:
    return repeat_photo(img, seed, green=green)


def test_alignment_recovers_the_camera_move() -> None:
    before_img = scene(1)
    after_img, truth = after_of(before_img, 1, green=False)
    before, after = prepare_array(before_img), prepare_array(after_img)
    alignment = align(before, after)
    assert alignment.ok, alignment.reason
    assert alignment.inliers >= 100 and alignment.inlier_ratio > 0.6
    assert alignment.overlap > 0.8
    # the estimated after->before homography inverts the true before->after warp
    estimated = pixel_homography(np.array(alignment.homography), before.size, after.size)
    points = np.float32([[100, 100], [500, 120], [320, 400]]).reshape(-1, 1, 2)
    round_trip = cv2.perspectiveTransform(cv2.perspectiveTransform(points, truth), estimated)
    assert np.abs(round_trip - points).max() < 2.0  # pixels
    # the shared area is (nearly) the whole before frame, and a sensible part of the after frame
    assert alignment.before_box[2] > 0.85 and alignment.after_box[2] > 0.8


def test_change_detection_finds_new_vegetation_and_ignores_lighting() -> None:
    before_img = scene(2)
    after_img, _ = after_of(before_img, 2, green=True)
    result = analyze_pair(prepare_array(before_img), prepare_array(after_img))
    change = result.change
    assert change is not None
    assert change.luminance_shift > 15  # the after photo is brighter...
    true_share = np.pi * GREEN_AXES[0] * GREEN_AXES[1] / (W * H)
    assert true_share * 0.7 < change.changed_share < true_share * 2  # ...but that is not "change"
    assert change.green_cover_after - change.green_cover_before > true_share * 0.6
    top = change.regions[0]
    assert top.kind == "more_green"
    cx, cy = (top.x + top.w / 2) * W, (top.y + top.h / 2) * H
    assert abs(cx - GREEN_CENTRE[0]) < 40 and abs(cy - GREEN_CENTRE[1]) < 40


def test_unchanged_scene_reports_little_change() -> None:
    before_img = scene(3)
    after_img, _ = after_of(before_img, 3, green=False)
    change = analyze_pair(prepare_array(before_img), prepare_array(after_img)).change
    assert change is not None
    assert change.changed_share < 0.03
    assert abs(change.green_delta_pp) < 2


def test_different_scenes_do_not_align_and_get_no_change_record() -> None:
    result = analyze_pair(prepare_array(scene(4)), prepare_array(scene(5)))
    assert not result.alignment.ok and result.alignment.reason
    assert result.change is None
    assert rank_score(0.9, result.alignment.as_dict()) < rank_score(0.5, _ok_alignment())


def _ok_alignment() -> dict[str, object]:
    return {"ok": True, "inliers": 40, "inlier_ratio": 0.5, "overlap": 0.8}


def test_featureless_images_fail_gracefully() -> None:
    flat = np.full((H, W, 3), 128, np.uint8)
    result = analyze_pair(prepare_array(flat), prepare_array(flat))
    assert not result.alignment.ok and "features" in (result.alignment.reason or "")


def test_bytes_entry_point_and_bad_input() -> None:
    before_img = scene(6)
    after_img, _ = after_of(before_img, 6, green=True)
    result = analyze_pair_bytes(encode(before_img), encode(after_img)).as_dict()
    assert result["alignment"]["ok"] and result["change"]["regions"]
    assert result["before_size"] == [W, H]
    with pytest.raises(ImageDecodeError):
        prepare(b"not an image")


def test_large_photos_are_analysed_at_working_size() -> None:
    big = cv2.resize(scene(7), (2400, 1800))
    assert max(prepare_array(big).size) == 1024


def test_benchmark_correct_pair_ranks_first() -> None:
    """PLAN Phase 7 'Done when': the correct pair ranks first >= 80% of the time.

    Every after photo is ranked against every before photo (8 scenes, so 7 distractors each) with
    the production score; no SigLIP here, so geometry alone must pick the right one."""
    n = 8
    befores = [prepare_array(scene(100 + s)) for s in range(n)]
    afters = [
        prepare_array(after_of(scene(100 + s), 100 + s, green=s % 2 == 0)[0]) for s in range(n)
    ]
    correct = 0
    for i, after in enumerate(afters):
        scores = [rank_score(None, align(before, after).as_dict()) for before in befores]
        correct += int(np.argmax(scores)) == i
    assert correct / n >= 0.8
