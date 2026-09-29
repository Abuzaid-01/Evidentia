"""Phase 7 integration tests: before/after candidates (PostGIS + pgvector SQL), worker analysis,
human confirmation, pairs as claim evidence, and comparisons in published reports.

Real Postgres/Redis. Cloudinary is never contacted: the worker's rendition download is replaced
by synthetic repeat photography (evidentia_ml.synthetic), and URLs are signed offline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

VILLAGE = (12.9716, 77.5946)


def auth(user: str, org: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev.{user}.{org}.{role}"}


def _photo(
    world: dict[str, Any],
    name: str,
    day: datetime,
    *,
    vector_text: str,
    site: str | None = "site",
    offset_m: float = 0.0,
    gps: bool = True,
) -> uuid.UUID:
    """A processed photo with a capture date, position and a SigLIP-like image embedding."""
    from evidentia_core.db.models import Asset, Embedding
    from evidentia_core.db.session import sync_system_session
    from evidentia_core.domain.enums import (
        AssetState,
        EmbeddingKind,
        ProvenanceSource,
        ResourceType,
    )
    from evidentia_ml.embeddings import HashEmbedder

    asset_id = uuid.uuid4()
    with sync_system_session() as session:
        session.add(
            Asset(
                id=asset_id,
                organization_id=world["org_id"],
                project_id=uuid.UUID(world["project"]),
                site_id=uuid.UUID(world[site]) if site else None,
                resource_type=ResourceType.IMAGE,
                public_id=f"evidentia/test/{asset_id}",
                cloudinary_version=1727000000,
                original_filename=f"{name}.jpg",
                format="jpg",
                width=4000,
                height=3000,
                sha256=uuid.uuid4().hex * 2,
                state=AssetState.READY,
                caption=f"{name} photo",
                capture_time=day,
                capture_time_source=ProvenanceSource.EXIF,
                latitude=VILLAGE[0] + offset_m / 111_000 if gps else None,
                longitude=VILLAGE[1] if gps else None,
                location_source=ProvenanceSource.EXIF if gps else ProvenanceSource.NONE,
                reviewed_at=datetime.now(UTC),
            )
        )
        session.flush()
        session.add(
            Embedding(
                organization_id=world["org_id"],
                asset_id=asset_id,
                kind=EmbeddingKind.IMAGE,
                model=HashEmbedder.model_name,
                vector=HashEmbedder().embed_texts([vector_text])[0],
                source_hash="test",
            )
        )
        session.commit()
    world["names"][asset_id] = name
    return asset_id


@pytest.fixture
async def w(client: httpx.AsyncClient, org: str) -> dict[str, Any]:
    manager = auth("asha", org, "manager")
    project = (
        await client.post("/v1/projects", headers=manager, json={"name": "Community Water Access"})
    ).json()
    sites = [
        (
            await client.post(
                f"/v1/projects/{project['id']}/sites",
                headers=manager,
                json={"name": name, "code": code, "latitude": VILLAGE[0], "longitude": VILLAGE[1]},
            )
        ).json()
        for name, code in (("Village A", "A"), ("Village B", "B"))
    ]
    me = (await client.get("/v1/me", headers=manager)).json()
    world: dict[str, Any] = {
        "org": org,
        "org_id": uuid.UUID(me["organization"]["id"]),
        "project": project["id"],
        "site": sites[0]["id"],
        "other_site": sites[1]["id"],
        "manager": manager,
        "author": auth("ravi", org, "contributor"),
        "reviewer": auth("meera", org, "reviewer"),
        "names": {},
    }
    aug = lambda d: datetime(2026, 8, d, 9, tzinfo=UTC)  # noqa: E731
    sep = lambda d: datetime(2026, 9, d, 9, tzinfo=UTC)  # noqa: E731
    world["before_trench"] = _photo(
        world, "trench_before", aug(1), vector_text="open trench pipe soil"
    )
    world["before_tank"] = _photo(
        world, "tank_before", aug(2), vector_text="water tank concrete base"
    )
    world["after_trench"] = _photo(
        world, "trench_after", sep(20), vector_text="open trench pipe soil grass"
    )
    # never candidates: another site, or too far away
    world["other_site_before"] = _photo(
        world, "other_site", aug(1), vector_text="open trench pipe soil", site="other_site"
    )
    world["far_before"] = _photo(
        world, "far", aug(3), vector_text="open trench pipe soil", offset_m=900
    )
    return world


def _synthetic_renditions(monkeypatch: pytest.MonkeyPatch, w: dict[str, Any]) -> None:
    from evidentia_ai.providers import ImageInput
    from evidentia_ml.synthetic import jpeg, repeat_photo, scene
    from evidentia_worker.tasks import before_after as worker

    trench = scene(11)
    images = {
        w["before_trench"]: jpeg(trench),
        w["after_trench"]: jpeg(repeat_photo(trench, 11, green=True)[0]),
        w["before_tank"]: jpeg(scene(12)),
    }
    monkeypatch.setattr(
        worker,
        "model_input",
        lambda session, asset, ctx: ImageInput(images[asset.id], "image/jpeg"),
    )


async def _suggest(client: httpx.AsyncClient, w: dict[str, Any], **extra: Any) -> dict[str, Any]:
    body = {
        "baseline_from": "2026-07-01",
        "baseline_to": "2026-08-31",
        "endline_from": "2026-09-01",
        "endline_to": "2026-09-30",
        **extra,
    }
    r = await client.post(
        f"/v1/projects/{w['project']}/before-after/suggest", headers=w["author"], json=body
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _analysed(
    client: httpx.AsyncClient, w: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> dict[str, dict[str, Any]]:
    """Suggest + run the worker on every queued pair. Returns pairs keyed by before-photo name."""
    from evidentia_worker.tasks.before_after import analyze_pair

    _synthetic_renditions(monkeypatch, w)
    out = await _suggest(client, w)
    for pair in out["pairs"]:
        assert analyze_pair(pair["id"]) == "analyzed"
    listed = (
        await client.get(f"/v1/projects/{w['project']}/before-after", headers=w["author"])
    ).json()
    return {w["names"][uuid.UUID(p["before"]["id"])]: p for p in listed}


async def test_candidates_use_site_distance_windows_and_similarity(
    client: httpx.AsyncClient, w: dict[str, Any], enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    from evidentia_core import tasks

    out = await _suggest(client, w)
    pairs = out["pairs"]
    # the one endline photo at Village A anchors; baselines come from the same site only
    befores = {
        (w["names"][uuid.UUID(p["after"]["id"])], w["names"][uuid.UUID(p["before"]["id"])])
        for p in pairs
    }
    assert ("trench_after", "trench_before") in befores and (
        "trench_after",
        "tank_before",
    ) in befores
    assert not {b for _, b in befores} & {"other_site", "far"}  # other site / 900 m away
    trench = [p for p in pairs if w["names"][uuid.UUID(p["after"]["id"])] == "trench_after"]
    ranked = sorted(trench, key=lambda p: -p["rank_score"])
    assert w["names"][uuid.UUID(ranked[0]["before"]["id"])] == "trench_before"  # SigLIP proposes
    assert ranked[0]["similarity"] > ranked[1]["similarity"]
    assert ranked[0]["days_apart"] == 50 and ranked[0]["distance_m"] == pytest.approx(0, abs=1)
    assert all(p["status"] == "candidate" and p["alignment_grade"] is None for p in pairs)
    assert out["created"] == len(pairs) and out["queued"] == len(pairs)
    assert {name for name, _ in enqueued} == {tasks.ANALYZE_PAIR}

    again = await _suggest(client, w)  # idempotent: same pairs, nothing new
    assert again["created"] == 0 and {p["id"] for p in again["pairs"]} == {p["id"] for p in pairs}

    # the minimum gap between the photos is enforced (the baselines are 48 to 50 days earlier)
    assert (await _suggest(client, w, min_gap_days=60))["pairs"] == []

    # a wider distance limit admits the far photo
    wide = await _suggest(client, w, max_distance_m=2000)
    assert "far" in {w["names"][uuid.UUID(p["before"]["id"])] for p in wide["pairs"]}

    # anchor mode: before photos for one after photo only
    anchored = await _suggest(client, w, anchor_asset_id=str(w["after_trench"]), per_anchor=1)
    assert [w["names"][uuid.UUID(p["before"]["id"])] for p in anchored["pairs"]] == [
        "trench_before"
    ]

    # default windows: split the site's capture dates when none are given
    default = (
        await client.post(
            f"/v1/projects/{w['project']}/before-after/suggest",
            headers=w["author"],
            json={"site_id": w["site"]},
        )
    ).json()
    assert default["windows"]["baseline_from"] == "2026-08-01"
    assert default["windows"]["endline_to"] == "2026-09-20"


async def test_worker_verifies_geometry_measures_change_and_records_lineage(
    client: httpx.AsyncClient,
    w: dict[str, Any],
    enqueued: list[tuple[str, tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    by_before = await _analysed(client, w, monkeypatch)
    right, wrong = by_before["trench_before"], by_before["tank_before"]
    # geometry decides: the true pair ranks first, the look-alike fails verification
    assert right["alignment_grade"] in {"strong", "partial"} and right["status"] == "analyzed"
    assert wrong["alignment_grade"] == "none" and wrong["rank_score"] < 0.1 < right["rank_score"]
    assert right["green_delta_pp"] > 2 and "green cover increased" in right["change_summary"]
    assert "not measured" in wrong["change_summary"]

    detail = (await client.get(f"/v1/before-after/{right['id']}", headers=w["author"])).json()
    assert detail["alignment"]["homography"] and detail["alignment"]["before_size"] == [640, 480]
    assert detail["changes"]["regions"][0]["kind"] == "more_green"
    assert detail["limitations"][0].startswith("Visible change between two photographs")
    assert (
        f"l_authenticated:evidentia:test:{w['after_trench']}" in detail["composite_transformation"]
    )
    assert detail["public_composite_transformation"].startswith("e_pixelate_faces")
    assert "/image/authenticated/s--" in detail["composite_url"]  # signed
    assert detail["before_url"] and detail["after_url"]

    # lineage: both composites are derivatives of the before photo
    asset = (await client.get(f"/v1/assets/{w['before_trench']}", headers=w["author"])).json()
    purposes = {d["purpose"]: d for d in asset["derivatives"]}
    assert purposes["before_after"]["transformation"] == detail["composite_transformation"]
    assert purposes["before_after_public"]["generative"] is False

    # idempotent per analysis version; forced re-analysis is allowed until a decision is made
    from evidentia_worker.tasks.before_after import analyze_pair

    assert analyze_pair(right["id"]) == "analyzed"
    r = await client.post(f"/v1/before-after/{right['id']}/analyze", headers=w["reviewer"])
    assert r.status_code == 200


async def test_confirmed_pair_backs_a_claim_and_appears_in_reports(
    client: httpx.AsyncClient,
    w: dict[str, Any],
    enqueued: list[tuple[str, tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    by_before = await _analysed(client, w, monkeypatch)
    right, wrong = by_before["trench_before"], by_before["tank_before"]
    author, reviewer, manager = w["author"], w["reviewer"], w["manager"]

    # decisions: reviewers only; unaligned pairs need a note; rejection needs a note
    assert (
        await client.post(f"/v1/before-after/{right['id']}/confirm", headers=author, json={})
    ).status_code == 403
    r = await client.post(f"/v1/before-after/{wrong['id']}/confirm", headers=reviewer, json={})
    assert r.status_code == 422 and "could not be aligned" in r.json()["error"]["message"]
    assert (
        await client.post(f"/v1/before-after/{wrong['id']}/reject", headers=reviewer, json={})
    ).status_code == 422
    r = await client.post(
        f"/v1/before-after/{wrong['id']}/reject", headers=reviewer, json={"note": "different place"}
    )
    assert r.json()["status"] == "rejected"

    claim = (
        await client.post(
            f"/v1/projects/{w['project']}/claims",
            headers=author,
            json={
                "statement": "Grass is growing back along the backfilled trench at Village A",
                "claim_type": "progress",
                "site_id": w["site"],
            },
        )
    ).json()
    cid = claim["id"]
    # an unconfirmed comparison is not evidence
    r = await client.post(
        f"/v1/claims/{cid}/evidence", headers=author, json={"pair_id": right["id"]}
    )
    assert r.status_code == 422 and "confirm" in r.json()["error"]["message"]

    confirmed = await client.post(
        f"/v1/before-after/{right['id']}/confirm", headers=reviewer, json={"note": "same trench"}
    )
    assert confirmed.json()["status"] == "confirmed"
    link = await client.post(
        f"/v1/claims/{cid}/evidence", headers=author, json={"pair_id": right["id"]}
    )
    assert link.status_code == 201, link.text
    assert link.json()["pair_id"] == right["id"] and link.json()["asset_id"] == str(
        w["after_trench"]
    )
    dup = await client.post(
        f"/v1/claims/{cid}/evidence", headers=author, json={"pair_id": right["id"]}
    )
    assert dup.status_code == 409

    detail = (await client.get(f"/v1/claims/{cid}", headers=author)).json()
    assert detail["rule_check"]["passed"] and detail["rule_check"]["verified_support"] == 1
    assert (
        detail["evidence"][0]["verified"]
        and "before/after" in detail["evidence"][0]["pair_summary"]
    )
    graph = (await client.get(f"/v1/claims/{cid}/graph", headers=author)).json()
    assert any(n["type"] == "before_after" for n in graph["nodes"])
    assert {e["relation"] for e in graph["edges"]} >= {"before", "after", "supports"}

    # a pair used as evidence can no longer be rejected
    r = await client.post(
        f"/v1/before-after/{right['id']}/reject", headers=reviewer, json={"note": "changed my mind"}
    )
    assert r.status_code == 409

    assert (await client.post(f"/v1/claims/{cid}/submit", headers=author)).status_code == 200
    await client.post(f"/v1/claims/{cid}/validate", headers=author)
    approved = await client.post(f"/v1/claims/{cid}/approve", headers=reviewer, json={"note": "ok"})
    assert approved.json()["status"] == "approved", approved.text

    for audience in ("internal", "external"):
        rid = (
            await client.post(
                f"/v1/projects/{w['project']}/reports",
                headers=author,
                json={"title": f"{audience} report", "audience": audience},
            )
        ).json()["id"]
        await client.post(f"/v1/reports/{rid}/generate", headers=author)
        published = await client.post(f"/v1/reports/{rid}/publish", headers=manager)
        assert published.status_code == 201, published.text
        manifest = (
            await client.get(f"/v1/reports/{rid}/snapshots/1/manifest", headers=author)
        ).json()
        (comparison,) = manifest["comparisons"]
        assert comparison["ref"] == "B1" and comparison["claim_refs"] == ["C1"]
        assert comparison["confirmed_by"]["name"] == "Meera"
        assert comparison["decision_note"] == "same trench"
        assert comparison["limitations"] and comparison["alignment"]["grade"] != "none"
        refs = {a["ref"]: a["id"] for a in manifest["assets"]}
        assert refs[comparison["before_asset_ref"]] == str(w["before_trench"])
        assert refs[comparison["after_asset_ref"]] == str(w["after_trench"])
        assert manifest["evidence"][0]["pair_ref"] == "B1"
        figure = comparison["figure"]
        assert "l_authenticated:" in figure["transformation"] and figure["url"]
        assert figure["transformation"].startswith("e_pixelate_faces") == (audience == "external")
        assert any("before and after photographs" in lim["text"] for lim in manifest["limitations"])

        html = (await client.get(f"/v1/reports/{rid}/snapshots/1/html", headers=author)).json()[
            "html"
        ]
        assert 'id="B1"' in html and "Before and after" in html
        assert "D. Before/after comparisons" in html and "E. How this report was produced" in html
        assert comparison["limitations"][0] in html
        verify = (await client.get(f"/v1/reports/{rid}/snapshots/1/verify", headers=author)).json()
        assert verify["identical"] is True

    audit = (await client.get("/v1/audit", headers=manager)).json()
    actions = {e["action"] for e in (audit["items"] if isinstance(audit, dict) else audit)}
    assert {
        "before_after.suggested",
        "before_after.analyzed",
        "before_after.confirmed",
        "before_after.rejected",
    } <= actions


async def test_manual_pairs_and_tenant_isolation(
    client: httpx.AsyncClient, w: dict[str, Any], enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    from evidentia_core import tasks

    url = f"/v1/projects/{w['project']}/before-after"
    body = {"before_asset_id": str(w["before_trench"]), "after_asset_id": str(w["after_trench"])}
    created = await client.post(url, headers=w["author"], json=body)
    assert created.status_code == 201, created.text
    pair = created.json()
    assert pair["origin"] == "manual" and pair["days_apart"] == 50
    assert pair["distance_m"] == pytest.approx(0, abs=1)
    assert (tasks.ANALYZE_PAIR, (pair["id"],)) in enqueued
    dup = await client.post(url, headers=w["author"], json=body)
    assert dup.status_code == 409 and dup.json()["error"]["details"]["pair_id"] == pair["id"]
    same = {"before_asset_id": str(w["before_trench"]), "after_asset_id": str(w["before_trench"])}
    assert (await client.post(url, headers=w["author"], json=same)).status_code == 422
    stranger = {"before_asset_id": str(uuid.uuid4()), "after_asset_id": str(w["after_trench"])}
    assert (await client.post(url, headers=w["author"], json=stranger)).status_code == 422
    # viewers read, contributors create
    viewer = auth("vic", w["org"], "viewer")
    assert (await client.post(url, headers=viewer, json=body)).status_code == 403
    listed = await client.get(f"{url}?asset_id={w['after_trench']}", headers=viewer)
    assert [p["id"] for p in listed.json()] == [pair["id"]]
    # confirming before analysis is refused
    r = await client.post(f"/v1/before-after/{pair['id']}/confirm", headers=w["reviewer"], json={})
    assert r.status_code == 409

    outsider = auth("x", f"other{uuid.uuid4().hex[:6]}", "manager")
    assert (await client.get(f"/v1/before-after/{pair['id']}", headers=outsider)).status_code == 404
    assert (await client.get(url, headers=outsider)).status_code == 404
