"""Before/after composite: one signed Cloudinary URL showing both photos side by side.

The before photo is the base; the after photo is an `l_authenticated:` layer (allowed only because
the whole URL is signed). Each side is cropped to the area both photos share, as measured by our
alignment, so the panels show the same part of the scene:

    <crop before>/c_fill,W,H/c_pad to 2W+gap wide (no scaling: the height already fits)
      /l_authenticated:<after>/<crop after>/c_fill,W,H/fl_layer_apply,g_east
      /c_pad to add a white caption strip/<two text labels>

Crops use relative coordinates (floats, as Cloudinary requires for all four of x/y/w/h), so they
hold for any stored size and orientation. The transformation string is the lineage record: it names
both public_ids and every step. External outputs pixelate faces in both photos first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cloudinary.utils

from evidentia_cloudinary.delivery import DeliveryUrl

PANEL_W, PANEL_H, GAP, STRIP_H = 800, 600, 16, 56
FONT = "Arial_26_bold"
REDACT = "e_pixelate_faces:12"
_LABEL_SAFE = re.compile(r"[^A-Za-z0-9 .\-]")


@dataclass(frozen=True)
class Side:
    public_id: str
    box: tuple[float, float, float, float]  # x, y, w, h in 0..1 (shared area of this photo)
    label: str  # e.g. "BEFORE 12 Aug 2026"


def layer_id(public_id: str) -> str:
    """Overlay ids replace folder slashes with colons."""
    return public_id.replace("/", ":")


def _f(value: float) -> str:
    return f"{min(1.0, max(0.0, value)):.4f}"


def _crop(box: tuple[float, float, float, float]) -> str:
    x, y, w, h = box
    w = max(0.05, min(w, 1.0 - x))
    h = max(0.05, min(h, 1.0 - y))
    if (x, y, w, h) == (0.0, 0.0, 1.0, 1.0):
        return ""
    return f"c_crop,x_{_f(x)},y_{_f(y)},w_{_f(w)},h_{_f(h)}/"


def _label(text: str) -> str:
    """Text layer content: only safe characters (no commas/slashes needing double escaping)."""
    clean = " ".join(_LABEL_SAFE.sub("", text).split())[:60] or "photo"
    return clean.replace(" ", "%20")


def composite_transformation(before: Side, after: Side, *, redact: bool = False) -> str:
    pre = f"{REDACT}/" if redact else ""
    fill = f"c_fill,g_center,w_{PANEL_W},h_{PANEL_H}"
    width = 2 * PANEL_W + GAP
    return "/".join(
        [
            f"{pre}{_crop(before.box)}{fill}",
            f"c_pad,w_{width},h_{PANEL_H},g_west,b_white",
            f"l_authenticated:{layer_id(after.public_id)}",
            f"{pre}{_crop(after.box)}{fill}",
            "fl_layer_apply,g_east",
            f"c_pad,w_{width},h_{PANEL_H + STRIP_H},g_north,b_white",
            f"co_black,l_text:{FONT}:{_label(before.label)}",
            "fl_layer_apply,g_south_west,x_16,y_14",
            f"co_black,l_text:{FONT}:{_label(after.label)}",
            f"fl_layer_apply,g_south_west,x_{PANEL_W + GAP + 16},y_14",
            "q_auto",
        ]
    )


def signed_url(before_public_id: str, transformation: str, *, variant: str) -> DeliveryUrl:
    """Sign a stored composite transformation (replayed exactly as recorded for lineage)."""
    url, _ = cloudinary.utils.cloudinary_url(
        before_public_id,
        resource_type="image",
        type="authenticated",
        sign_url=True,
        secure=True,
        raw_transformation=transformation,
        format="jpg",
    )
    return DeliveryUrl(
        url=url,
        variant=variant,
        transformation=transformation,
        named_transformation=None,
        format="jpg",
    )


def composite_url(before: Side, after: Side, *, redact: bool = False) -> DeliveryUrl:
    return signed_url(
        before.public_id,
        composite_transformation(before, after, redact=redact),
        variant="before_after_public" if redact else "before_after",
    )
