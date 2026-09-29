"""The named transformations Evidentia uses, defined once.

Named transformations are created in the account by the bootstrap script and marked
`allowed_for_strict`, so the account can run with **strict transformations** enabled (nobody can
invent new, costly transformations by editing a URL). Every rendition we deliver or feed to a model
is one of these, which keeps lineage exact: purpose -> named transformation -> definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Variant = Literal[
    "thumb",
    "review",
    "ai",
    "public_redacted",
    "social_1x1",
    "social_4x5",
    "social_9x16",
    "social_16x9",
]


@dataclass(frozen=True)
class NamedTransformation:
    name: str  # referenced in URLs as t_<name>
    definition: str
    format: str | None  # delivery format/extension; None lets f_auto decide
    description: str


IMAGE: dict[str, NamedTransformation] = {
    "thumb": NamedTransformation(
        "ev_thumb", "c_fill,g_auto,w_480,h_360/f_auto,q_auto", None, "Grid thumbnail, smart-cropped"
    ),
    "review": NamedTransformation(
        "ev_review", "c_limit,w_1600,h_1600/f_auto,q_auto", None, "Reviewer / detail view"
    ),
    "ai": NamedTransformation(
        "ev_ai", "c_limit,w_1280,h_1280/q_auto:good", "jpg", "Model input: bounded size, JPEG"
    ),
    "public_redacted": NamedTransformation(
        "ev_public_redacted",
        "e_pixelate_faces:12/c_limit,w_1600,h_1600/f_auto,q_auto",
        None,
        "Anything shown outside the organization: faces pixelated",
    ),
}

VIDEO: dict[str, NamedTransformation] = {
    "thumb": NamedTransformation(
        "ev_video_poster", "so_50p/c_fill,g_auto,w_480,h_360/q_auto", "jpg", "Poster frame at 50%"
    ),
    "review": NamedTransformation(
        "ev_video_review", "c_limit,w_1280,h_1280/q_auto", "mp4", "Review playback rendition"
    ),
    "ai": NamedTransformation(
        "ev_video_frame_ai",
        "so_50p/c_limit,w_1280,h_1280/q_auto:good",
        "jpg",
        "Frame at 50% for models",
    ),
    "public_redacted": NamedTransformation(
        "ev_video_public", "c_limit,w_1280,h_1280/q_auto", "mp4", "External video rendition"
    ),
}

SOCIAL: dict[str, NamedTransformation] = {
    "social_1x1": NamedTransformation(
        "ev_social_1x1",
        "c_fill,g_auto,w_1080,h_1080/f_auto,q_auto",
        None,
        "Square social card (1:1)",
    ),
    "social_4x5": NamedTransformation(
        "ev_social_4x5",
        "c_fill,g_auto,w_1080,h_1350/f_auto,q_auto",
        None,
        "Portrait social card (4:5)",
    ),
    "social_9x16": NamedTransformation(
        "ev_social_9x16",
        "c_fill,g_auto,w_1080,h_1920/f_auto,q_auto",
        None,
        "Story / Reel / Shorts (9:16)",
    ),
    "social_16x9": NamedTransformation(
        "ev_social_16x9",
        "c_fill,g_auto,w_1920,h_1080/f_auto,q_auto",
        None,
        "Landscape social card (16:9)",
    ),
    "social_1x1_redacted": NamedTransformation(
        "ev_social_1x1_redacted",
        "e_pixelate_faces:12/c_fill,g_auto,w_1080,h_1080/f_auto,q_auto",
        None,
        "Redacted square social card (1:1)",
    ),
    "social_4x5_redacted": NamedTransformation(
        "ev_social_4x5_redacted",
        "e_pixelate_faces:12/c_fill,g_auto,w_1080,h_1350/f_auto,q_auto",
        None,
        "Redacted portrait social card (4:5)",
    ),
    "social_9x16_redacted": NamedTransformation(
        "ev_social_9x16_redacted",
        "e_pixelate_faces:12/c_fill,g_auto,w_1080,h_1920/f_auto,q_auto",
        None,
        "Redacted Story / Reel (9:16)",
    ),
    "social_16x9_redacted": NamedTransformation(
        "ev_social_16x9_redacted",
        "e_pixelate_faces:12/c_fill,g_auto,w_1920,h_1080/f_auto,q_auto",
        None,
        "Redacted landscape social card (16:9)",
    ),
}

ALL: tuple[NamedTransformation, ...] = (*IMAGE.values(), *VIDEO.values(), *SOCIAL.values())

# Renditions generated at upload time (eager) so the first view is instant.
EAGER_IMAGE: tuple[str, ...] = ("thumb", "review")
EAGER_VIDEO: tuple[str, ...] = ("thumb",)


def for_resource(resource_type: str) -> dict[str, NamedTransformation]:
    return VIDEO if resource_type == "video" else IMAGE


def eager_param(resource_type: str, *, named: bool) -> str:
    """Build the `eager` upload parameter (pipe-separated), e.g. `t_ev_thumb|t_ev_review`."""
    table = for_resource(resource_type)
    wanted = EAGER_VIDEO if resource_type == "video" else EAGER_IMAGE
    parts = []
    for variant in wanted:
        nt = table[variant]
        step = f"t_{nt.name}" if named else nt.definition
        parts.append(f"{step}/{nt.format}" if nt.format else step)
    return "|".join(parts)
