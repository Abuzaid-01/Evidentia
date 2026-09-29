"""Before/after comparison: geometric verification, alignment and visible-change measurement.

Given two photos that may show the same place on two dates:

1. **Geometric verification.** SIFT keypoints + Lowe's ratio test + a RANSAC homography. The number
   and share of inlier matches say whether the photos really show the same scene from a similar
   viewpoint, which SigLIP similarity alone cannot (two different trenches look alike to it).
2. **Alignment.** The homography maps the *after* photo onto the *before* photo's frame. It is
   stored in normalised coordinates (both images scaled to the unit square) so it applies to any
   rendition size: the API, the web slider and the Cloudinary composite all reuse it.
3. **Visible change.** On the aligned, brightness-normalised pair: an SSIM dissimilarity map plus a
   chroma difference, cleaned up morphologically -> changed share of the shared area and the main
   change regions. Green cover is measured with the Excess Green index (ExG = 2g - r - b on
   chromaticity), a transparent colour rule rather than a learned model.

Everything here measures pixels. The numbers describe what the camera saw on two dates; they are
never an impact metric (PLAN.md §5), and callers attach rule-derived limitations to every result.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

ANALYSIS_VERSION = "before-after-2026-09-28.1"
ALIGN_METHOD = "sift+ratio+ransac-homography"
CHANGE_METHOD = "ssim+chroma+exg"

WORK_MAX_SIDE = 1024  # images are analysed at most this large (long side)
SIFT_FEATURES = 4000
RATIO_TEST = 0.75
RANSAC_REPROJ_PX = 4.0
MIN_GOOD_MATCHES = 12
MIN_INLIERS = 15
MIN_INLIER_RATIO = 0.2
MIN_OVERLAP = 0.25

SSIM_SIGMA = 1.5
DISSIMILARITY_THRESHOLD = 0.3  # (1 - SSIM) / 2 above this counts as structural change
CHROMA_THRESHOLD = 18.0  # Lab a/b distance (8-bit scale) above this counts as colour change
MIN_REGION_SHARE = 0.0015  # change blobs smaller than this share of the shared area are noise
MAX_REGIONS = 8
EXG_THRESHOLD = 0.1  # chromaticity ExG above this = vegetation
EXG_MIN_BRIGHTNESS = 90  # R+G+B (0..765); darker pixels have unreliable chromaticity
REGION_GREEN_SHIFT = 0.25  # share of a region that turned green (or stopped being green)


class ImageDecodeError(ValueError):
    """The bytes are not a decodable image."""


@dataclass
class Prepared:
    """A decoded, working-size image with its SIFT features (computed once, reused per pair)."""

    bgr: np.ndarray
    gray: np.ndarray
    keypoints: tuple[Any, ...] = ()
    descriptors: np.ndarray | None = None

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.gray.shape[:2]
        return w, h


@dataclass
class Alignment:
    ok: bool
    method: str
    keypoints_before: int
    keypoints_after: int
    good_matches: int
    inliers: int
    inlier_ratio: float
    overlap: float  # share of the before frame covered by the warped after frame
    # after-normalised -> before-normalised, row-major 3x3 with h22 = 1
    homography: list[list[float]] | None
    rotation_deg: float | None
    scale: float | None
    perspective: float | None
    # [x, y, w, h] in normalised coordinates: the shared area in each photo (for crops/composites)
    before_box: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])
    after_box: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeRegion:
    x: float
    y: float
    w: float
    h: float
    area_share: float  # of the shared area
    kind: str  # changed | more_green | less_green


@dataclass
class Change:
    method: str
    shared_share: float  # share of the before frame that both photos cover
    ssim_mean: float
    changed_share: float  # share of the shared area that changed visibly
    luminance_shift: float  # mean L (after - before), 0..255 scale, before normalisation
    green_cover_before: float
    green_cover_after: float
    regions: list[ChangeRegion]

    @property
    def green_delta_pp(self) -> float:
        return round((self.green_cover_after - self.green_cover_before) * 100, 1)

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["green_delta_pp"] = self.green_delta_pp
        return out


@dataclass
class PairAnalysis:
    version: str
    alignment: Alignment
    change: Change | None
    before_size: tuple[int, int]
    after_size: tuple[int, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "alignment": self.alignment.as_dict(),
            "change": self.change.as_dict() if self.change else None,
            "before_size": list(self.before_size),
            "after_size": list(self.after_size),
        }


# --- preparation ---------------------------------------------------------------------------------


def _cv2() -> Any:
    import cv2  # imported lazily: the API process only needs this module's types

    return cv2


def prepare(data: bytes, *, max_side: int = WORK_MAX_SIDE) -> Prepared:
    cv2 = _cv2()
    array = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(array, cv2.IMREAD_COLOR) if array.size else None
    if bgr is None:
        raise ImageDecodeError("not a decodable image")
    return prepare_array(bgr, max_side=max_side)


def prepare_array(bgr: np.ndarray, *, max_side: int = WORK_MAX_SIDE) -> Prepared:
    cv2 = _cv2()
    h, w = bgr.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        bgr = cv2.resize(bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # Local contrast equalisation makes keypoints less sensitive to the lighting of each day.
    equalised = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    sift = cv2.SIFT_create(nfeatures=SIFT_FEATURES)
    keypoints, descriptors = sift.detectAndCompute(equalised, None)
    return Prepared(bgr=bgr, gray=gray, keypoints=tuple(keypoints), descriptors=descriptors)


# --- geometry ------------------------------------------------------------------------------------


def _scale_matrix(w: int, h: int) -> np.ndarray:
    return np.diag([float(w), float(h), 1.0])


def _normalise_h(h_px: np.ndarray, before: Prepared, after: Prepared) -> np.ndarray:
    """Pixel homography (after px -> before px) to unit-square coordinates."""
    wb, hb = before.size
    wa, ha = after.size
    h_norm = np.linalg.inv(_scale_matrix(wb, hb)) @ h_px @ _scale_matrix(wa, ha)
    return h_norm / h_norm[2, 2]


def pixel_homography(
    h_norm: np.ndarray, before_size: tuple[int, int], after_size: tuple[int, int]
) -> np.ndarray:
    h_px = _scale_matrix(*before_size) @ h_norm @ np.linalg.inv(_scale_matrix(*after_size))
    return h_px / h_px[2, 2]


def _warp_points(h: np.ndarray, points: np.ndarray) -> np.ndarray:
    homogeneous = np.hstack([points, np.ones((len(points), 1))]) @ h.T
    return homogeneous[:, :2] / homogeneous[:, 2:3]


_UNIT_CORNERS = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])


def _overlap(h_norm: np.ndarray, grid: int = 256) -> float:
    """Share of the before frame covered by the warped after frame (rasterised polygon clip)."""
    cv2 = _cv2()
    corners = _warp_points(h_norm, _UNIT_CORNERS)
    if not np.all(np.isfinite(corners)):
        return 0.0
    mask = np.zeros((grid, grid), dtype=np.uint8)
    polygon = np.clip(corners * grid, -10 * grid, 11 * grid).astype(np.int32)
    cv2.fillPoly(mask, [polygon], 1)
    return float(mask.mean())


def _is_convex(points: np.ndarray) -> bool:
    signs = set()
    for i in range(4):
        a, b, c = points[i], points[(i + 1) % 4], points[(i + 2) % 4]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        signs.add(cross > 0)
    return len(signs) == 1


def _failed(before: Prepared, after: Prepared, reason: str, **extra: Any) -> Alignment:
    values: dict[str, Any] = {
        "good_matches": 0,
        "inliers": 0,
        "inlier_ratio": 0.0,
        **extra,
    }
    return Alignment(
        ok=False,
        method=ALIGN_METHOD,
        keypoints_before=len(before.keypoints),
        keypoints_after=len(after.keypoints),
        overlap=0.0,
        homography=None,
        rotation_deg=None,
        scale=None,
        perspective=None,
        reason=reason,
        **values,
    )


def align(before: Prepared, after: Prepared) -> Alignment:
    """Geometric verification + homography (after -> before). Never raises on bad input."""
    cv2 = _cv2()
    if (
        before.descriptors is None
        or after.descriptors is None
        or len(before.keypoints) < MIN_GOOD_MATCHES
        or len(after.keypoints) < MIN_GOOD_MATCHES
    ):
        return _failed(before, after, "Too few distinctive features to match")

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    pairs = matcher.knnMatch(after.descriptors, before.descriptors, k=2)
    good = [
        m
        for m, *rest in (p for p in pairs if len(p) == 2)
        if m.distance < RATIO_TEST * rest[0].distance
    ]
    if len(good) < MIN_GOOD_MATCHES:
        return _failed(before, after, "Too few matching features", good_matches=len(good))

    src = np.float32([after.keypoints[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([before.keypoints[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    h_px, mask = cv2.findHomography(
        src, dst, cv2.RANSAC, RANSAC_REPROJ_PX, maxIters=5000, confidence=0.995
    )
    if h_px is None or mask is None:
        return _failed(
            before, after, "No consistent geometry between the photos", good_matches=len(good)
        )
    inliers = int(mask.sum())
    ratio = inliers / len(good)

    h_norm = _normalise_h(h_px, before, after)
    affine = h_px[:2, :2] / h_px[2, 2]
    det = float(np.linalg.det(affine))
    rotation = math.degrees(math.atan2(affine[1, 0], affine[0, 0]))
    scale = math.sqrt(abs(det))
    perspective = float(max(abs(h_norm[2, 0]), abs(h_norm[2, 1])))
    overlap = _overlap(h_norm)
    corners = _warp_points(h_norm, _UNIT_CORNERS)

    reason = None
    if det <= 0 or not 0.25 <= scale <= 4.0:
        reason = "Implausible geometry (mirror or extreme zoom)"
    elif not _is_convex(corners):
        reason = "Implausible geometry (folded perspective)"
    elif inliers < MIN_INLIERS or ratio < MIN_INLIER_RATIO:
        reason = "Too few geometrically consistent matches: probably not the same scene"
    elif overlap < MIN_OVERLAP:
        reason = "The photos barely overlap"

    before_box, after_box = [0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0]
    if reason is None:
        before_box, after_box = _shared_boxes(h_norm)
    return Alignment(
        ok=reason is None,
        method=ALIGN_METHOD,
        keypoints_before=len(before.keypoints),
        keypoints_after=len(after.keypoints),
        good_matches=len(good),
        inliers=inliers,
        inlier_ratio=round(ratio, 4),
        overlap=round(overlap, 4),
        homography=[[round(float(v), 8) for v in row] for row in h_norm],
        rotation_deg=round(rotation, 2),
        scale=round(scale, 4),
        perspective=round(perspective, 5),
        before_box=before_box,
        after_box=after_box,
        reason=reason,
    )


def _box(points: np.ndarray) -> list[float]:
    lo = np.clip(points.min(axis=0), 0.0, 1.0)
    hi = np.clip(points.max(axis=0), 0.0, 1.0)
    return [round(float(v), 4) for v in (lo[0], lo[1], hi[0] - lo[0], hi[1] - lo[1])]


def _shared_boxes(h_norm: np.ndarray) -> tuple[list[float], list[float]]:
    """Axis-aligned shared area in both photos: where the warped after frame lands in the before
    frame, and that area mapped back into the after frame."""
    warped = np.clip(_warp_points(h_norm, _UNIT_CORNERS), 0.0, 1.0)
    before_box = _box(warped)
    x, y, w, h = before_box
    box_corners = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])
    after_box = _box(_warp_points(np.linalg.inv(h_norm), box_corners))
    return before_box, after_box


# --- change detection ------------------------------------------------------------------------------


def _ssim_map(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    cv2 = _cv2()
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2

    def blur(x: np.ndarray) -> np.ndarray:
        return cv2.GaussianBlur(x, (11, 11), SSIM_SIGMA)

    mu_a, mu_b = blur(a), blur(b)
    var_a = blur(a * a) - mu_a**2
    var_b = blur(b * b) - mu_b**2
    cov = blur(a * b) - mu_a * mu_b
    return ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / (
        (mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2)
    )


def vegetation_mask(bgr: np.ndarray) -> np.ndarray:
    """Excess Green on chromaticity coordinates (Woebbecke et al.): 2g - r - b."""
    f = bgr.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    total = r + g + b
    safe = np.maximum(total, 1.0)
    exg = (2 * g - r - b) / safe
    return (exg > EXG_THRESHOLD) & (total > EXG_MIN_BRIGHTNESS)


def detect_change(before: Prepared, after: Prepared, alignment: Alignment) -> Change | None:
    """Visible change inside the area both photos cover. None when the pair is not aligned."""
    if not alignment.ok or alignment.homography is None:
        return None
    cv2 = _cv2()
    wb, hb = before.size
    h_px = pixel_homography(np.array(alignment.homography), before.size, after.size)
    warped = cv2.warpPerspective(after.bgr, h_px, (wb, hb), flags=cv2.INTER_LINEAR)
    footprint = cv2.warpPerspective(
        np.full(after.gray.shape, 255, np.uint8), h_px, (wb, hb), flags=cv2.INTER_NEAREST
    )
    # stay clear of the warped border, where interpolation smears pixels
    valid = cv2.erode(footprint, np.ones((7, 7), np.uint8)) > 0
    shared = float(valid.mean())
    if valid.sum() < 1000:
        return None

    lab_b = cv2.cvtColor(before.bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab_a = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB).astype(np.float32)
    lb, la = lab_b[..., 0], lab_a[..., 0]
    mu_b, sd_b = float(lb[valid].mean()), float(lb[valid].std()) or 1.0
    mu_a, sd_a = float(la[valid].mean()), float(la[valid].std()) or 1.0
    la_norm = (la - mu_a) / sd_a * sd_b + mu_b  # brightness/contrast matched to the before photo

    ssim = _ssim_map(lb, la_norm)
    dissimilarity = cv2.GaussianBlur(((1.0 - ssim) / 2.0).astype(np.float32), (7, 7), 0)
    chroma = np.sqrt((lab_b[..., 1] - lab_a[..., 1]) ** 2 + (lab_b[..., 2] - lab_a[..., 2]) ** 2)
    chroma = cv2.GaussianBlur(chroma, (7, 7), 0)
    raw = ((dissimilarity > DISSIMILARITY_THRESHOLD) | (chroma > CHROMA_THRESHOLD)) & valid
    mask = cv2.morphologyEx(raw.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)) & valid.astype(
        np.uint8
    )

    veg_b = vegetation_mask(before.bgr) & valid
    veg_a = vegetation_mask(warped) & valid
    valid_px = float(valid.sum())

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = MIN_REGION_SHARE * valid_px
    regions: list[ChangeRegion] = []
    kept = np.zeros_like(mask, dtype=bool)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        component = labels == label
        kept |= component
        shift = float(veg_a[component].mean() - veg_b[component].mean())
        kind = (
            "more_green"
            if shift > REGION_GREEN_SHIFT
            else "less_green"
            if shift < -REGION_GREEN_SHIFT
            else "changed"
        )
        x, y, w, h = (
            int(stats[label, k])
            for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT)
        )
        regions.append(
            ChangeRegion(
                x=round(x / wb, 4),
                y=round(y / hb, 4),
                w=round(w / wb, 4),
                h=round(h / hb, 4),
                area_share=round(area / valid_px, 4),
                kind=kind,
            )
        )
    regions.sort(key=lambda r: r.area_share, reverse=True)

    return Change(
        method=CHANGE_METHOD,
        shared_share=round(shared, 4),
        ssim_mean=round(float(ssim[valid].mean()), 4),
        changed_share=round(float(kept.sum()) / valid_px, 4),
        luminance_shift=round(mu_a - mu_b, 2),
        green_cover_before=round(float(veg_b.sum()) / valid_px, 4),
        green_cover_after=round(float(veg_a.sum()) / valid_px, 4),
        regions=regions[:MAX_REGIONS],
    )


def analyze_pair(before: Prepared, after: Prepared) -> PairAnalysis:
    alignment = align(before, after)
    return PairAnalysis(
        version=ANALYSIS_VERSION,
        alignment=alignment,
        change=detect_change(before, after, alignment),
        before_size=before.size,
        after_size=after.size,
    )


def analyze_pair_bytes(before: bytes, after: bytes) -> PairAnalysis:
    return analyze_pair(prepare(before), prepare(after))
