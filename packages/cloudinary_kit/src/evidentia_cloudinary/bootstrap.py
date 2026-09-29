"""Idempotent Cloudinary account setup ("configuration as code").

Creates or updates:
  * named transformations (marked allowed_for_strict),
  * signed upload presets for evidence images and videos,
  * structured metadata fields (optional).

Safe to run repeatedly. Prints a checklist of the console-only settings at the end.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import cloudinary.api
import cloudinary.exceptions as cex

from evidentia_cloudinary import transformations

IMAGE_FORMATS = "jpg,jpeg,png,heic,heif,webp"
VIDEO_FORMATS = "mp4,mov,webm"

PRESETS: dict[str, dict[str, Any]] = {
    "evidentia_image": {
        "unsigned": False,
        "type": "authenticated",
        "resource_type": "image",
        "allowed_formats": IMAGE_FORMATS,
        "overwrite": False,
        "use_filename": False,
        "unique_filename": True,
        "tags": "evidentia",
    },
    "evidentia_video": {
        "unsigned": False,
        "type": "authenticated",
        "resource_type": "video",
        "allowed_formats": VIDEO_FORMATS,
        "overwrite": False,
        "use_filename": False,
        "unique_filename": True,
        "tags": "evidentia",
    },
}

METADATA_FIELDS: list[dict[str, Any]] = [
    {"external_id": "ev_project_id", "type": "string", "label": "Evidentia project"},
    {"external_id": "ev_site_id", "type": "string", "label": "Evidentia site"},
    {"external_id": "ev_activity", "type": "string", "label": "Activity"},
    {
        "external_id": "ev_verification_status",
        "type": "enum",
        "label": "Verification status",
        "datasource": {
            "values": [
                {"external_id": "unreviewed", "value": "Unreviewed"},
                {"external_id": "needs_review", "value": "Needs review"},
                {"external_id": "verified", "value": "Verified"},
                {"external_id": "rejected", "value": "Rejected"},
            ]
        },
    },
]

CONSOLE_CHECKLIST = [
    "Settings > Security > enable 'Strict transformations' (named ones are pre-approved).",
    "Settings > Security > keep 'Resource list' restricted; never enable unsigned uploads for evidence.",
    "Settings > Add-ons > register free tiers: Cloudinary AI Vision / Analyze API, "
    "OCR Text Detection and Extraction, and one auto-tagging add-on (optional).",
    "Settings > Webhook notifications > if you add a trigger, keep auth_scheme 'default'.",
    "Settings > Backups (paid plans) > enable automatic backup for production evidence.",
]


@dataclass
class BootstrapReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _named_transformations(report: BootstrapReport, dry_run: bool) -> None:
    for nt in transformations.ALL:
        label = f"transformation t_{nt.name}"
        try:
            existing = cloudinary.api.transformation(nt.name)
        except cex.NotFound:
            existing = None
        except cex.Error as exc:
            report.errors.append(f"{label}: {exc}")
            continue
        if dry_run:
            report.skipped.append(f"{label} (dry run)")
            continue
        try:
            if existing is None:
                cloudinary.api.create_transformation(nt.name, nt.definition)
                cloudinary.api.update_transformation(nt.name, allowed_for_strict=True)
                report.created.append(label)
            else:
                cloudinary.api.update_transformation(
                    nt.name, unsafe_update=nt.definition, allowed_for_strict=True
                )
                report.updated.append(label)
        except cex.Error as exc:
            report.errors.append(f"{label}: {exc}")


def _upload_presets(report: BootstrapReport, dry_run: bool) -> None:
    for name, settings in PRESETS.items():
        label = f"upload preset {name}"
        try:
            cloudinary.api.upload_preset(name)
            exists = True
        except cex.NotFound:
            exists = False
        except cex.Error as exc:
            report.errors.append(f"{label}: {exc}")
            continue
        if dry_run:
            report.skipped.append(f"{label} (dry run)")
            continue
        try:
            if exists:
                cloudinary.api.update_upload_preset(name, **settings)
                report.updated.append(label)
            else:
                cloudinary.api.create_upload_preset(name=name, **settings)
                report.created.append(label)
        except cex.Error as exc:
            report.errors.append(f"{label}: {exc}")


def _metadata_fields(report: BootstrapReport, dry_run: bool) -> None:
    try:
        existing = {
            f["external_id"]
            for f in cloudinary.api.list_metadata_fields().get("metadata_fields", [])
        }
    except cex.Error as exc:
        report.errors.append(f"structured metadata: {exc}")
        return
    for spec in METADATA_FIELDS:
        label = f"metadata field {spec['external_id']}"
        if spec["external_id"] in existing:
            report.skipped.append(f"{label} (exists)")
            continue
        if dry_run:
            report.skipped.append(f"{label} (dry run)")
            continue
        try:
            cloudinary.api.add_metadata_field(spec)
            report.created.append(label)
        except cex.Error as exc:
            report.errors.append(f"{label}: {exc}")


def run(
    *, structured_metadata: bool, dry_run: bool = False, echo: Callable[[str], None] = print
) -> BootstrapReport:
    report = BootstrapReport()
    _named_transformations(report, dry_run)
    _upload_presets(report, dry_run)
    if structured_metadata:
        _metadata_fields(report, dry_run)

    for title, items in (
        ("created", report.created),
        ("updated", report.updated),
        ("skipped", report.skipped),
        ("ERRORS", report.errors),
    ):
        if items:
            echo(f"\n{title}:")
            for item in items:
                echo(f"  - {item}")
    echo("\nConsole-only settings to check:")
    for item in CONSOLE_CHECKLIST:
        echo(f"  [ ] {item}")
    return report
