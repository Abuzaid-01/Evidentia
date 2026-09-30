"""Manifest -> HTML. Pure and deterministic: the same manifest always yields byte-identical HTML,
which is what makes a published snapshot verifiable. Never read the clock or the database here.

Each manifest format has its own frozen template: a snapshot always re-renders with the template of
the format it was published in, so redesigning the report never breaks "verify" for older snapshots
(tests pin the old bytes). Changes to an existing template must stay additive (e.g. Phase 7
`comparisons` render nothing when the key is absent); visual redesigns get a new format + template."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from evidentia_core.domain.reports import MANIFEST_VERSION, SECTIONS, manifest_hash
from evidentia_core.domain.video import span_label
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

# manifest format -> (template, renderer version recorded on the snapshot)
TEMPLATES: dict[str, tuple[str, str]] = {
    "report-manifest/1": ("report.html.j2", "report-html-2026-09-28.1"),
    "report-manifest/2": ("report_v2.html.j2", "report-html-2026-09-30.1"),
}
RENDERER_VERSION = TEMPLATES[MANIFEST_VERSION][1]
GALLERY_LIMIT = 24


def _fmt_date(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%d %b %Y").lstrip("0")


def _period(start: str | None, end: str | None) -> str:
    if start and end:
        return f"{_fmt_date(start)} to {_fmt_date(end)}"
    if start:
        return f"from {_fmt_date(start)}"
    if end:
        return f"until {_fmt_date(end)}"
    return "all dates"


def _label(value: str | None) -> str:
    return (value or "").replace("_", " ")


def _pct(value: object) -> str:
    if not isinstance(value, int | float):
        return "—"
    return f"{round(float(value) * 100)}%"


def _span_label(span: object) -> str:
    if not isinstance(span, dict):
        return ""
    start, end = span.get("start_ms"), span.get("end_ms")
    if not isinstance(start, int) or not isinstance(end, int):
        return ""
    return span_label(start, end)


_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
_env.filters.update(date=_fmt_date, label=_label, span_label=_span_label, pct=_pct)
_env.globals.update(period=_period)


def _template(manifest: Mapping[str, Any]) -> tuple[str, str]:
    version = str(manifest.get("manifest_version") or "report-manifest/1")
    if version not in TEMPLATES:
        raise ValueError(f"no report template for manifest format {version!r}")
    return TEMPLATES[version]


def renderer_version(manifest: Mapping[str, Any]) -> str:
    """The renderer that owns this manifest's format (recorded on the snapshot at publish)."""
    return _template(manifest)[1]


def render_html(manifest: Mapping[str, Any]) -> str:
    template, version = _template(manifest)
    assets = {a["ref"]: a for a in manifest.get("assets") or []}
    claims = {c["ref"]: c for c in manifest.get("claims") or []}
    metrics = {m["ref"]: m for m in manifest.get("metrics") or []}
    evidence = manifest.get("evidence") or []
    figures: list[dict[str, Any]] = []
    seen: set[str] = set()
    proves: dict[str, list[str]] = {}  # asset ref -> claim refs it supports
    for item in evidence:
        # before/after evidence is shown as its composite, not as a single photo
        if item["relation"] != "supports" or item.get("pair_ref"):
            continue
        proves.setdefault(item["asset_ref"], [])
        if item["claim_ref"] not in proves[item["asset_ref"]]:
            proves[item["asset_ref"]].append(item["claim_ref"])
        if item["asset_ref"] in seen:
            continue
        seen.add(item["asset_ref"])
        figures.append({"evidence": item, "asset": assets[item["asset_ref"]]})
    figures.sort(key=lambda f: (f["asset"].get("capture_time") or "", f["asset"]["ref"]))
    return _env.get_template(template).render(
        m=manifest,
        sections=dict(SECTIONS),
        claims=claims,
        metrics=metrics,
        evidence={e["ref"]: e for e in evidence},
        assets=assets,
        figures=figures[:GALLERY_LIMIT],
        hidden_figures=max(0, len(figures) - GALLERY_LIMIT),
        comparisons=manifest.get("comparisons") or [],
        manifest_sha256=manifest_hash(manifest),
        renderer_version=version,
        # used by the format-2 template only
        proves=proves,
        claim_photos={
            ref: _unique(
                e["asset_ref"]
                for e in evidence
                if e["claim_ref"] == ref and e["relation"] == "supports"
            )
            for ref in claims
        },
        glance=_at_a_glance(manifest),
    )


def _unique(items: Any) -> list[str]:
    return list(dict.fromkeys(items))


def _at_a_glance(manifest: Mapping[str, Any]) -> dict[str, Any]:
    assets = manifest.get("assets") or []
    captured = sorted(a["capture_time"] for a in assets if a.get("capture_time"))
    approvers = _unique(
        c["approved_by"]["name"] for c in manifest.get("claims") or [] if c.get("approved_by")
    )
    sites = _unique(
        [a["site"] for a in assets if a.get("site")]
        + [c["site"] for c in manifest.get("claims") or [] if c.get("site")]
    )
    return {
        "claims": len(manifest.get("claims") or []),
        "photos": len(assets),
        "metrics": len(manifest.get("metrics") or []),
        "comparisons": len(manifest.get("comparisons") or []),
        "approvers": approvers,
        "sites": sites,
        "first_capture": captured[0] if captured else None,
        "last_capture": captured[-1] if captured else None,
    }
