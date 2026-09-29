"""Manifest -> HTML. Pure and deterministic: the same manifest always yields byte-identical HTML,
which is what makes a published snapshot verifiable. Never read the clock or the database here.

Template changes must stay additive: sections for newer manifest keys (e.g. Phase 7 `comparisons`)
render nothing when the key is absent, so snapshots published earlier still re-render to the exact
bytes they were hashed with (tests pin this)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from evidentia_core.domain.reports import SECTIONS, manifest_hash
from evidentia_core.domain.video import span_label
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

RENDERER_VERSION = "report-html-2026-09-28.1"
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


def render_html(manifest: Mapping[str, Any]) -> str:
    assets = {a["ref"]: a for a in manifest.get("assets") or []}
    evidence = manifest.get("evidence") or []
    figures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence:
        # before/after evidence is shown as its composite, not as a single photo
        if item["relation"] != "supports" or item["asset_ref"] in seen or item.get("pair_ref"):
            continue
        seen.add(item["asset_ref"])
        figures.append({"evidence": item, "asset": assets[item["asset_ref"]]})
    figures.sort(key=lambda f: (f["asset"].get("capture_time") or "", f["asset"]["ref"]))
    return _env.get_template("report.html.j2").render(
        m=manifest,
        sections=dict(SECTIONS),
        claims={c["ref"]: c for c in manifest.get("claims") or []},
        metrics={m["ref"]: m for m in manifest.get("metrics") or []},
        evidence={e["ref"]: e for e in evidence},
        assets=assets,
        figures=figures[:GALLERY_LIMIT],
        hidden_figures=max(0, len(figures) - GALLERY_LIMIT),
        comparisons=manifest.get("comparisons") or [],
        manifest_sha256=manifest_hash(manifest),
        renderer_version=RENDERER_VERSION,
    )
