from __future__ import annotations

import copy
from typing import Any

import pytest
from evidentia_core.domain.reports import MANIFEST_VERSION, manifest_hash
from evidentia_reporting import PdfRendererUnavailable, html_to_pdf, render_html


def manifest(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "report": {
            "id": "r1",
            "title": "Water access <Q3>",
            "audience": "internal",
            "period_start": "2026-08-01",
            "period_end": "2026-09-30",
            "project": {"id": "p1", "name": "Community Water Access"},
            "site": None,
        },
        "published": {
            "version": 1,
            "published_at": "2026-09-30T10:00:00+00:00",
            "published_by": {"id": "u1", "name": "Asha"},
        },
        "narrative": {
            "summary": [{"text": "142 households now collect piped water.", "cites": ["C1", "M1"]}],
            "overview": [],
            "generator": {
                "mode": "fallback",
                "provider": None,
                "model": None,
                "version": "w1",
                "edited_by": None,
            },
        },
        "limitations": [{"text": "Some metrics were counted from media.", "cites": ["M1"]}],
        "claims": [
            {
                "ref": "C1",
                "id": "c1",
                "statement": "142 households now collect piped water",
                "claim_type": "outcome",
                "support_level": "verified",
                "site": "Village A",
                "period_start": None,
                "period_end": None,
                "author": {"id": "u2", "name": "Ravi"},
                "approved_by": {"id": "u3", "name": "Meera"},
                "approved_at": "2026-09-29T09:00:00+00:00",
                "decision_note": None,
                "validation": None,
                "rule_check": {"passed": True},
                "evidence_refs": ["E1"],
                "metric_refs": ["M1"],
                "app_url": "http://localhost:3000/claims/c1",
            }
        ],
        "metrics": [
            {
                "ref": "M1",
                "id": "m1",
                "name": "Households connected",
                "value": "142",
                "unit": "households",
                "method": "Door-to-door survey",
                "source_type": "field_survey",
                "source_reference": "Form HH-7",
                "period_start": None,
                "period_end": None,
                "site": None,
            }
        ],
        "evidence": [
            {
                "ref": "E1",
                "link_id": "l1",
                "claim_ref": "C1",
                "asset_ref": "A1",
                "relation": "supports",
                "note": None,
                "span": None,
                "observation": {
                    "id": "o1",
                    "ontology_type": "activity",
                    "subject": "pipe_installation",
                    "predicate": "depicted",
                    "status": "verified",
                    "confidence": 0.93,
                    "source_kind": "ai",
                    "source_provider": "gemini",
                    "reviewer": None,
                    "reviewed_at": None,
                    "run": {
                        "provider": "gemini",
                        "model": "gemini-2.5-flash",
                        "model_version": None,
                        "prompt_version": "vision-extract-1",
                        "schema_version": "1",
                        "taxonomy_version": 1,
                    },
                },
            }
        ],
        "assets": [
            {
                "ref": "A1",
                "id": "a1",
                "public_id": "evidentia/org/proj/abc",
                "cloudinary_asset_id": None,
                "cloudinary_version": 1727000000,
                "resource_type": "image",
                "format": "jpg",
                "sha256": "ab" * 32,
                "original_filename": "pipe.jpg",
                "caption": "Workers lower a pipe",
                "capture_time": "2026-08-12T09:00:00+00:00",
                "capture_time_source": "exif",
                "location_source": "exif",
                "site": "Village A",
                "reviewed_at": None,
                "figure": {
                    "variant": "thumb",
                    "named_transformation": "ev_thumb",
                    "transformation": "c_fill,g_auto,w_480,h_360/f_auto,q_auto",
                    "url": None,
                },
                "app_url": None,
            }
        ],
        "timeline": [],
    }
    base.update(overrides)
    return base


def test_render_is_deterministic_and_traceable() -> None:
    m = manifest()
    html = render_html(m)
    assert html == render_html(copy.deepcopy(m))
    assert manifest_hash(m) in html
    assert 'href="#C1"' in html and 'id="C1"' in html and 'id="M1"' in html
    assert "t_ev_thumb = c_fill,g_auto,w_480,h_360/f_auto,q_auto" in html
    assert "gemini/gemini-2.5-flash" in html
    assert "Water access &lt;Q3&gt;" in html  # autoescaped
    assert "Version 1, published 30 Sep 2026 by Asha" in html


def test_draft_and_external_markers() -> None:
    html = render_html(
        manifest(published=None, report={**manifest()["report"], "audience": "external"})
    )
    assert "DRAFT PREVIEW" in html and "Faces are pixelated" in html


def test_changing_the_manifest_changes_the_html() -> None:
    m = manifest()
    changed = copy.deepcopy(m)
    changed["metrics"][0]["value"] = "143"
    assert render_html(m) != render_html(changed)


def test_pdf_from_html() -> None:
    try:
        pdf = html_to_pdf(render_html(manifest()))
    except PdfRendererUnavailable as exc:
        pytest.skip(str(exc))
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000


# Byte-exact HTML of the fixture manifests as rendered before Phase 7. Published snapshots are
# verified by re-rendering, so template changes must leave older manifests untouched.
PRE_PHASE7_HTML_SHA256 = {
    "internal": "85546b42f9e67c15711dfab073acf03fcfbe43f1583f2dc88ec1319f29473c68",
    "external_draft": "ae5c58e45e8e3b6b60147e7624d0ca0ea6d3ff7a47d2c050fee4f63c68693609",
}


def test_older_manifests_render_byte_identically() -> None:
    import hashlib

    external = manifest(published=None)
    external["report"]["audience"] = "external"
    for key, m in (("internal", manifest()), ("external_draft", external)):
        digest = hashlib.sha256(render_html(m).encode()).hexdigest()
        assert digest == PRE_PHASE7_HTML_SHA256[key], key


def test_before_after_comparison_renders_with_composite_and_limitations() -> None:
    m = manifest()
    m["assets"].append(
        {**m["assets"][0], "ref": "A2", "id": "a2", "capture_time": "2026-09-20T09:00:00+00:00"}
    )
    m["evidence"][0].update(pair_ref="B1", observation=None)  # pair links carry no observation
    m["comparisons"] = [
        {
            "ref": "B1",
            "id": "p1",
            "before_asset_ref": "A1",
            "after_asset_ref": "A2",
            "claim_refs": ["C1"],
            "evidence_refs": ["E1"],
            "days_apart": 39,
            "confirmed_by": {"id": "u3", "name": "Meera"},
            "confirmed_at": "2026-09-29T09:00:00+00:00",
            "decision_note": "same trench",
            "analysis_version": "before-after-test",
            "alignment": {
                "grade": "strong",
                "method": "sift",
                "inliers": 300,
                "inlier_ratio": 0.82,
                "overlap": 0.95,
            },
            "change": {
                "summary": "Visible change across a small part of the shared view; green cover increased.",
                "method": "ssim+chroma+exg",
                "changed_share": 0.061,
                "green_cover_before": 0.1,
                "green_cover_after": 0.16,
                "ssim_mean": 0.7,
            },
            "limitations": ["Visible change between two photographs is not impact."],
            "figure": {
                "variant": "before_after",
                "transformation": "c_fill/l_authenticated:x/fl_layer_apply",
                "url": "https://res.cloudinary.com/x/composite.jpg",
            },
        }
    ]
    html = render_html(m)
    assert 'id="B1"' in html and "https://res.cloudinary.com/x/composite.jpg" in html
    assert "Visible change between two photographs is not impact." in html
    assert 'before/after comparison <a href="#B1">B1</a>' in html  # evidence table
    assert "changed 6% of the shared view" in html and "green cover 10% → 16%" in html
    assert "c_fill/l_authenticated:x/fl_layer_apply" in html  # lineage in the appendix
    assert "E. How this report was produced" in html
    # the pair's photo is shown as the composite, not again as a single gallery figure
    assert 'id="fig-A1"' not in html
