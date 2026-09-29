"""Synthetic repeat photography for tests and the pairing benchmark's self-check.

A "scene" is a procedural image (soil-like noise, shapes, lines). A repeat photo is the same scene
from a slightly different camera position (random perspective warp) under different light,
optionally with a new patch of vegetation. Real benchmarks use labelled field photos
(`infra/eval/before_after_eval.py`); this module only makes the algorithms testable offline.
"""

from __future__ import annotations

import numpy as np

W, H = 640, 480
GREEN_CENTRE, GREEN_AXES = (int(W * 0.3), int(H * 0.6)), (90, 60)


def scene(seed: int) -> np.ndarray:
    import cv2

    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(90, 150, (H, W, 3)).astype(np.uint8), (0, 0), 3)
    img[..., 2] = np.clip(img[..., 2].astype(int) + 25, 0, 255)  # brownish soil
    for _ in range(60):
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        x, y = int(rng.integers(0, W)), int(rng.integers(0, H))
        kind = rng.integers(0, 3)
        if kind == 0:
            corner = (x + int(rng.integers(10, 80)), y + int(rng.integers(10, 80)))
            cv2.rectangle(img, (x, y), corner, color, -1)
        elif kind == 1:
            cv2.circle(img, (x, y), int(rng.integers(5, 40)), color, -1)
        else:
            end = (int(rng.integers(0, W)), int(rng.integers(0, H)))
            cv2.line(img, (x, y), end, color, int(rng.integers(1, 6)))
    return np.clip(img + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)


def repeat_photo(img: np.ndarray, seed: int, *, green: bool) -> tuple[np.ndarray, np.ndarray]:
    """Returns (after photo, true pixel homography before -> after)."""
    import cv2

    rng = np.random.default_rng(seed + 1000)
    src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    dst = (src + rng.uniform(-0.05, 0.05, (4, 2)) * [W, H]).astype(np.float32)
    matrix = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(img, matrix, (W, H), borderMode=cv2.BORDER_REFLECT)
    out = np.clip(out.astype(float) * 1.15 + 12, 0, 255).astype(np.uint8)  # brighter day
    if green:
        mask = np.zeros((H, W), np.uint8)
        cv2.ellipse(mask, GREEN_CENTRE, GREEN_AXES, 0, 0, 360, 1, -1)
        leaves = np.clip(np.array([40, 150, 50]) + rng.normal(0, 18, (H, W, 3)), 0, 255)
        out[mask.astype(bool)] = leaves[mask.astype(bool)].astype(np.uint8)
    return out, matrix


def jpeg(img: np.ndarray, quality: int = 92) -> bytes:
    import cv2

    ok, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("could not encode JPEG")
    return buffer.tobytes()
