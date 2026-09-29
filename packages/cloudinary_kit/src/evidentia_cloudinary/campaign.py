"""Campaign Studio: social format transformations, text overlays, brand frames,
generative presentation effects and video reel splicing (Phase 8).

Rules:
1. Every external/campaign output MUST include face redaction (e_pixelate_faces:12).
2. Generative effects (b_gen_fill, e_gen_restore) flag `generative=True` and add an
   "ILLUSTRATIVE - ENHANCED FOR PRESENTATION" watermark. They are blocked from claims.
3. Every generated rendition records its exact transformation string as a Derivative
   for complete lineage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import cloudinary.utils

from evidentia_cloudinary.delivery import DeliveryUrl

SocialAspectRatio = Literal["1:1", "4:5", "9:16", "16:9"]

DIMENSIONS: dict[SocialAspectRatio, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}

REDACT = "e_pixelate_faces:12"
FONT_STAT = "Arial_54_bold"
FONT_HEADLINE = "Arial_36_bold"
FONT_BRAND = "Arial_22_bold"
FONT_WATERMARK = "Arial_20_bold"

_LABEL_SAFE = re.compile(r"[^A-Za-z0-9 .,\-!?:%#]")


def layer_id(public_id: str) -> str:
    """Overlay IDs replace folder slashes with colons for Cloudinary."""
    return public_id.replace("/", ":")


def _label(text: str, max_len: int = 70) -> str:
    """Format text for Cloudinary l_text layer with safe URL encoding."""
    clean = " ".join(_LABEL_SAFE.sub("", text).split())[:max_len] or "Evidence"
    return clean.replace(" ", "%20").replace(",", "%2C").replace("/", "%2F")


def _num(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s else "0"


@dataclass(frozen=True)
class ReelSegment:
    public_id: str
    start_s: float
    end_s: float
    caption: str | None = None


def social_card_transformation(
    aspect_ratio: SocialAspectRatio = "1:1",
    headline: str = "",
    stat_text: str | None = None,
    brand_name: str | None = "EVIDENTIA VERIFIED",
    *,
    redact: bool = True,
    generative_fill: bool = False,
    generative_restore: bool = False,
) -> tuple[str, bool]:
    """Build a complete Cloudinary transformation string for a social media card.

    Returns (transformation_string, is_generative).
    """
    width, height = DIMENSIONS.get(aspect_ratio, (1080, 1080))
    is_generative = bool(generative_fill or generative_restore)

    steps: list[str] = []

    # 1. Generative restore (enhancement) if requested
    if generative_restore:
        steps.append("e_gen_restore")

    # 2. Mandatory face redaction for external/campaign media
    if redact:
        steps.append(REDACT)

    # 3. Canvas crop / pad (with generative fill if requested)
    if generative_fill:
        steps.append(f"c_pad,g_auto,w_{width},h_{height},b_gen_fill")
    else:
        steps.append(f"c_fill,g_auto,w_{width},h_{height}")

    # 4. Text overlays with vertical layout
    y_brand = 36
    y_headline = y_brand + 36
    y_stat = y_headline + 54

    # Brand tag (at bottom left)
    if brand_name:
        steps.append(f"co_rgb:94a3b8,l_text:{FONT_BRAND}:{_label(brand_name, 50)}")
        steps.append(f"fl_layer_apply,g_south_west,x_48,y_{y_brand}")

    # Headline (above brand)
    if headline:
        steps.append(f"co_white,l_text:{FONT_HEADLINE}:{_label(headline, 65)}")
        steps.append(f"fl_layer_apply,g_south_west,x_48,y_{y_headline}")

    # Stat / Highlight Metric (above headline, emerald green)
    if stat_text:
        steps.append(f"co_rgb:10b981,l_text:{FONT_STAT}:{_label(stat_text, 50)}")
        steps.append(f"fl_layer_apply,g_south_west,x_48,y_{y_stat}")

    # 5. Generative watermark / disclaimer if generative effects were used
    if is_generative:
        steps.append(
            f"co_rgb:f59e0b,l_text:{FONT_WATERMARK}:ILLUSTRATIVE%20-%20ENHANCED%20FOR%20PRESENTATION"
        )
        steps.append("fl_layer_apply,g_north_east,x_36,y_36")

    # 6. Optimized output
    steps.append("f_auto,q_auto")

    return "/".join(steps), is_generative


def video_reel_transformation(
    segments: list[ReelSegment],
    *,
    redact: bool = True,
    width: int = 1280,
    height: int = 720,
) -> str:
    """Build a Cloudinary transformation string splicing multiple video segments with fl_splice."""
    if not segments:
        raise ValueError("At least one video segment is required to build a reel")

    first = segments[0]
    steps: list[str] = []

    # Base clip
    if redact:
        steps.append(REDACT)
    steps.append(
        f"so_{_num(first.start_s)},eo_{_num(first.end_s)}/c_fill,g_auto,w_{width},h_{height}"
    )

    # Splice subsequent segments
    for seg in segments[1:]:
        splice_parts = [f"l_authenticated:{layer_id(seg.public_id)}"]
        if redact:
            splice_parts.append(REDACT)
        splice_parts.append(
            f"so_{_num(seg.start_s)},eo_{_num(seg.end_s)}/c_fill,g_auto,w_{width},h_{height}/fl_splice"
        )
        steps.append("/".join(splice_parts))
        steps.append("fl_layer_apply")

    steps.append("q_auto")
    return "/".join(steps)


def signed_campaign_url(
    public_id: str,
    transformation: str,
    *,
    resource_type: str = "image",
    format: str = "jpg",
    variant: str = "campaign",
) -> DeliveryUrl:
    """Sign a stored campaign transformation for secure delivery with full lineage."""
    url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        resource_type=resource_type,
        type="authenticated",
        sign_url=True,
        secure=True,
        raw_transformation=transformation,
        format=format,
    )
    return DeliveryUrl(
        url=url,
        variant=variant,
        transformation=transformation,
        named_transformation=None,
        format=format,
    )
