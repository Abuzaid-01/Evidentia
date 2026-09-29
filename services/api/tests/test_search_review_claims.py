"""Phase 3 + 4 integration tests: hybrid search, human review, claims and the evidence graph.

Real Postgres (RLS, pgvector, full-text) and Redis. Embeddings use the deterministic HashEmbedder,
LLMs are absent (rules-only planning, `not_checked` validation), Cloudinary is never contacted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration


def auth(user: str, org: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev.{user}.{org}.{role}"}


def _asset(
    org_id: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID | None, **kw: Any
) -> dict[str, Any]:
    return {"org_id": org_id, "project_id": project_id, "site_id": site_id, **kw}


def _seed(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert processed assets with observations, search documents and hash embeddings."""
    from evidentia_core.db.models import Asset, Embedding, Observation
    from evidentia_core.db.session import sync_system_session
    from evidentia_core.domain.enums import (
        AssetState,
        EmbeddingKind,
        ObservationStatus,
        OntologyType,
        ProvenanceSource,
        ResourceType,
        SourceKind,
    )
    from evidentia_core.domain.search_doc import ObservationText, build_search_text
    from evidentia_ml.embeddings import HashEmbedder

    embedder = HashEmbedder()
    labels = {
        "pipe_installation": "Pipe installation",
        "tank_construction": "Tank construction",
        "excavation": "Excavation",
    }
    out = []
    with sync_system_session() as session:
        for spec in specs:
            asset_id = uuid.uuid4()
            obs_rows = []
            for subject, status, conf in spec["activities"]:
                obs_rows.append(
                    Observation(
                        organization_id=spec["org_id"],
                        asset_id=asset_id,
                        ontology_type=OntologyType.ACTIVITY,
                        subject=subject,
                        predicate="depicted",
                        confidence=conf,
                        source_kind=SourceKind.AI,
                        source_provider="mock",
                        status=ObservationStatus(status),
                        value={"rationale": "seed"},
                    )
                )
            text = build_search_text(
                caption=spec["caption"],
                observations=[
                    ObservationText(
                        "activity", o.subject, "depicted", o.status.value, None, o.confidence
                    )
                    for o in obs_rows
                ],
                activity_labels=labels,
                site_name=None,
                filename=None,
                note=None,
            )
            verified = (
                sorted({o.subject for o in obs_rows if o.status == ObservationStatus.VERIFIED})
                or None
            )
            session.add(
                Asset(
                    id=asset_id,
                    organization_id=spec["org_id"],
                    project_id=spec["project_id"],
                    site_id=spec["site_id"],
                    resource_type=ResourceType(spec.get("type", "image")),
                    public_id=str(asset_id),
                    original_filename=f"{spec['name']}.jpg",
                    format="jpg",
                    state=AssetState(spec.get("state", "ready")),
                    caption=spec["caption"],
                    capture_time=spec["captured"],
                    capture_time_source=ProvenanceSource.EXIF,
                    search_text=text,
                    verified_activities=verified,
                    reviewed_at=datetime.now(UTC) if verified else None,
                    review_priority=spec.get("priority"),
                    review_reasons=spec.get("reasons"),
                    exact_duplicate_of_id=spec.get("duplicate_of"),
                    top_activity=obs_rows[0].subject if obs_rows else None,
                )
            )
            session.flush()
            session.add_all(obs_rows)
            for kind, source in (
                (EmbeddingKind.IMAGE, spec["image_words"]),
                (EmbeddingKind.TEXT, text),
            ):
                vector = embedder.embed_texts([source])[0]
                session.add(
                    Embedding(
                        organization_id=spec["org_id"],
                        asset_id=asset_id,
                        kind=kind,
                        model=embedder.model_name,
                        vector=vector,
                    )
                )
            session.flush()
            out.append({"id": asset_id, "observations": {o.subject: o.id for o in obs_rows}})
        session.commit()
    return out


@pytest.fixture
async def world(client: httpx.AsyncClient, org: str) -> dict[str, Any]:
    manager = auth("mgr", org, "manager")
    project = (
        await client.post("/v1/projects", headers=manager, json={"name": "Community Water Access"})
    ).json()
    site_a = (
        await client.post(
            f"/v1/projects/{project['id']}/sites",
            headers=manager,
            json={"name": "Village A", "code": "A"},
        )
    ).json()
    site_b = (
        await client.post(
            f"/v1/projects/{project['id']}/sites",
            headers=manager,
            json={"name": "Rampura", "code": "B"},
        )
    ).json()
    org_id = uuid.UUID((await client.get("/v1/me", headers=manager)).json()["organization"]["id"])
    pid, a, b = uuid.UUID(project["id"]), uuid.UUID(site_a["id"]), uuid.UUID(site_b["id"])

    pipe, tank, dig = _seed(
        [
            _asset(
                org_id,
                pid,
                a,
                name="pipe",
                caption="Workers lower a blue pipe into an open trench",
                activities=[("pipe_installation", "verified", 0.93)],
                image_words="blue pipe trench workers",
                captured=datetime(2026, 8, 12, 9, tzinfo=UTC),
            ),
            _asset(
                org_id,
                pid,
                b,
                name="tank",
                caption="Concrete water tank with scaffolding",
                activities=[("tank_construction", "proposed", 0.8)],
                image_words="concrete tank scaffolding",
                captured=datetime(2026, 8, 20, 9, tzinfo=UTC),
            ),
            _asset(
                org_id,
                pid,
                a,
                name="dig",
                caption="Excavator digging a trench",
                state="review_required",
                activities=[("excavation", "proposed", 0.55)],
                image_words="yellow excavator digging trench",
                captured=datetime(2026, 6, 5, 9, tzinfo=UTC),
                priority=0.7,
                reasons=["Top activity below threshold"],
            ),
        ]
    )
    (dup,) = _seed(
        [
            _asset(
                org_id,
                pid,
                a,
                name="pipe_copy",
                caption="Workers lower a blue pipe into an open trench",
                activities=[("pipe_installation", "proposed", 0.9)],
                image_words="blue pipe trench workers",
                captured=datetime(2026, 8, 15, 9, tzinfo=UTC),
                state="review_required",
                priority=0.3,
                reasons=["Exact duplicate of an existing asset"],
                duplicate_of=pipe["id"],
            ),
        ]
    )
    return {
        "org": org,
        "project": str(pid),
        "site_a": str(a),
        "site_b": str(b),
        "pipe": pipe,
        "tank": tank,
        "dig": dig,
        "dup": dup,
    }


# --- Phase 3: search ------------------------------------------------------------------------------------


async def test_natural_language_search_applies_filters_and_ranks(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    viewer = auth("v", world["org"], "viewer")
    r = await client.post(
        "/v1/search",
        headers=viewer,
        json={"project_id": world["project"], "query": "pipe installation at site A in August"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    f = body["plan"]["filters"]
    assert (
        f["site_ids"] == [world["site_a"]]
        and f["date_from"] == "2026-08-01"
        and f["activities"] == ["pipe_installation"]
    )
    ids = [x["asset"]["id"] for x in body["results"]]
    assert ids[0] == str(world["pipe"]["id"])  # verified match ranks first
    assert str(world["dup"]["id"]) in ids  # duplicate still found...
    assert ids.index(str(world["dup"]["id"])) > 0  # ...but ranked below the original
    assert str(world["tank"]["id"]) not in ids  # site B filtered out
    assert str(world["dig"]["id"]) not in ids  # June filtered out
    top = body["results"][0]
    assert "verified activity match" in top["reasons"]
    assert {"activity", "lexical", "visual"} <= set(top["contributions"])
    assert top["matched_observations"][0]["subject"] == "pipe_installation"


async def test_visual_and_semantic_retrieval_without_activity_words(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    r = await client.post(
        "/v1/search",
        headers=auth("v", world["org"], "viewer"),
        json={"project_id": world["project"], "query": "concrete scaffolding"},
    )
    results = r.json()["results"]
    assert results[0]["asset"]["id"] == str(world["tank"]["id"])
    assert "visual" in results[0]["contributions"]


async def test_filter_only_search_and_review_filter(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    r = await client.post(
        "/v1/search",
        headers=auth("v", world["org"], "viewer"),
        json={"project_id": world["project"], "query": "", "filters": {"needs_review": True}},
    )
    ids = {x["asset"]["id"] for x in r.json()["results"]}
    assert ids == {str(world["dig"]["id"]), str(world["dup"]["id"])}
    assert "structured" in r.json()["retrievers"]


async def test_search_is_tenant_isolated(client: httpx.AsyncClient, world: dict[str, Any]) -> None:
    other = auth("x", world["org"] + "zz", "admin")
    r = await client.post(
        "/v1/search", headers=other, json={"project_id": world["project"], "query": "pipe"}
    )
    assert r.status_code == 404


async def test_similar_images_and_feedback(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    viewer = auth("v", world["org"], "viewer")
    r = await client.post(
        "/v1/search/similar", headers=viewer, json={"asset_id": str(world["pipe"]["id"])}
    )
    similar = r.json()
    assert similar[0]["asset"]["id"] == str(world["dup"]["id"]) and similar[0]["similarity"] > 0.99
    assert str(world["pipe"]["id"]) not in {s["asset"]["id"] for s in similar}

    search = (
        await client.post(
            "/v1/search", headers=viewer, json={"project_id": world["project"], "query": "pipe"}
        )
    ).json()
    fb = await client.post(
        f"/v1/search/{search['query_id']}/feedback",
        headers=viewer,
        json={"asset_id": str(world["pipe"]["id"]), "action": "click", "rank": 1},
    )
    assert fb.status_code == 204


# --- Phase 4: review --------------------------------------------------------------------------------------


async def test_review_queue_order_and_roles(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    url = f"/v1/projects/{world['project']}/review-queue"
    assert (
        await client.get(url, headers=auth("c", world["org"], "contributor"))
    ).status_code == 403
    queue = (await client.get(url, headers=auth("r", world["org"], "reviewer"))).json()
    assert [q["asset"]["id"] for q in queue] == [str(world["dig"]["id"]), str(world["dup"]["id"])]
    assert queue[0]["pending_observations"] == 1


async def test_review_approve_add_complete(
    client: httpx.AsyncClient, world: dict[str, Any], enqueued: list[Any]
) -> None:
    reviewer = auth("r", world["org"], "reviewer")
    dig = world["dig"]
    r = await client.post(
        f"/v1/assets/{dig['id']}/observations",
        headers=reviewer,
        json={"ontology_type": "condition", "subject": "trench", "predicate": "open"},
    )
    assert (
        r.status_code == 201
        and r.json()["status"] == "verified"
        and r.json()["source_kind"] == "human"
    )

    r = await client.post(
        f"/v1/assets/{dig['id']}/review",
        headers=reviewer,
        json={
            "decisions": [
                {"observation_id": str(dig["observations"]["excavation"]), "decision": "approve"}
            ],
            "complete": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ready" and r.json()["verified_activities"] == ["excavation"]
    assert {name for name, _ in enqueued} >= {
        "evidentia.search.reindex_asset",
        "evidentia.cloudinary.sync_review",
    }

    detail = (await client.get(f"/v1/assets/{dig['id']}", headers=reviewer)).json()
    assert detail["state"] == "ready"
    history = (await client.get(f"/v1/assets/{dig['id']}/reviews", headers=reviewer)).json()
    assert [h["decision"] for h in history] == ["approve"]
    actions = [
        e["action"]
        for e in (await client.get("/v1/audit", headers=auth("m", world["org"], "manager"))).json()
    ]
    assert {"observation.approve", "observation.added", "asset.review_completed"} <= set(actions)

    # the verified-only search now finds it
    s = await client.post(
        "/v1/search",
        headers=reviewer,
        json={"project_id": world["project"], "query": "verified excavation"},
    )
    assert str(dig["id"]) in {x["asset"]["id"] for x in s.json()["results"]}


async def test_edit_supersedes_and_validates_taxonomy(
    client: httpx.AsyncClient, world: dict[str, Any], enqueued: list[Any]
) -> None:
    reviewer = auth("r", world["org"], "reviewer")
    tank = world["tank"]
    obs_id = str(tank["observations"]["tank_construction"])
    bad = await client.post(
        f"/v1/assets/{tank['id']}/review",
        headers=reviewer,
        json={
            "decisions": [
                {"observation_id": obs_id, "decision": "edit", "edit": {"subject": "rocket_launch"}}
            ]
        },
    )
    assert bad.status_code == 422
    r = await client.post(
        f"/v1/assets/{tank['id']}/review",
        headers=reviewer,
        json={
            "decisions": [
                {
                    "observation_id": obs_id,
                    "decision": "edit",
                    "edit": {"subject": "completed_infrastructure"},
                    "note": "roof finished",
                }
            ]
        },
    )
    new_id = r.json()["replacements"][obs_id]
    observations = {
        o["id"]: o
        for o in (await client.get(f"/v1/assets/{tank['id']}", headers=reviewer)).json()[
            "observations"
        ]
    }
    assert obs_id not in observations  # superseded (history kept, hidden from current view)
    assert (
        observations[new_id]["subject"] == "completed_infrastructure"
        and observations[new_id]["status"] == "verified"
    )
    again = await client.post(
        f"/v1/assets/{tank['id']}/review",
        headers=reviewer,
        json={"decisions": [{"observation_id": obs_id, "decision": "approve"}]},
    )
    assert again.status_code == 409


# --- Phase 4: claims & evidence graph -----------------------------------------------------------------------


async def test_claim_lifecycle_rules_four_eyes_and_graph(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    author = auth("ravi", world["org"], "contributor")
    reviewer = auth("meera", world["org"], "reviewer")
    claim = (
        await client.post(
            f"/v1/projects/{world['project']}/claims",
            headers=author,
            json={
                "statement": "Pipes were laid in an open trench at Site A",
                "claim_type": "descriptive",
                "site_id": world["site_a"],
            },
        )
    ).json()
    assert claim["support_level"] == "unsupported"
    cid = claim["id"]

    # unverified evidence is not enough
    await client.post(
        f"/v1/claims/{cid}/evidence",
        headers=author,
        json={
            "asset_id": str(world["tank"]["id"]),
            "observation_id": str(world["tank"]["observations"]["tank_construction"]),
            "relation": "context",
        },
    )
    assert (await client.post(f"/v1/claims/{cid}/submit", headers=author)).status_code == 422

    link = await client.post(
        f"/v1/claims/{cid}/evidence",
        headers=author,
        json={
            "asset_id": str(world["pipe"]["id"]),
            "observation_id": str(world["pipe"]["observations"]["pipe_installation"]),
        },
    )
    assert link.status_code == 201
    dup = await client.post(
        f"/v1/claims/{cid}/evidence",
        headers=author,
        json={
            "asset_id": str(world["pipe"]["id"]),
            "observation_id": str(world["pipe"]["observations"]["pipe_installation"]),
        },
    )
    assert dup.status_code == 409

    submitted = (await client.post(f"/v1/claims/{cid}/submit", headers=author)).json()
    assert submitted["status"] == "in_review" and submitted["support_level"] == "proposed"
    assert (
        await client.post(f"/v1/claims/{cid}/approve", headers=author, json={})
    ).status_code == 403  # role
    assert (
        await client.post(f"/v1/claims/{cid}/approve", headers=reviewer, json={})
    ).status_code == 422  # not validated

    validated = (await client.post(f"/v1/claims/{cid}/validate", headers=author)).json()
    assert validated["validation_verdict"] == "not_checked"  # no LLM configured in tests
    approved = (
        await client.post(
            f"/v1/claims/{cid}/approve", headers=reviewer, json={"note": "clear photo"}
        )
    ).json()
    assert approved["status"] == "approved" and approved["support_level"] == "verified"

    frozen = await client.post(
        f"/v1/claims/{cid}/evidence", headers=author, json={"asset_id": str(world["dig"]["id"])}
    )
    assert frozen.status_code == 409

    graph = (await client.get(f"/v1/claims/{cid}/graph", headers=reviewer)).json()
    types = {n["type"] for n in graph["nodes"]}
    assert types == {"claim", "asset", "observation"}
    assert any(e["relation"] == "supports" for e in graph["edges"])

    detail = (await client.get(f"/v1/claims/{cid}", headers=reviewer)).json()
    assert [e["verified"] for e in detail["evidence"]] == [False, True]


async def test_outcome_claim_needs_sourced_metric_matching_numbers(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    manager = auth("mgr", world["org"], "manager")
    claim = (
        await client.post(
            f"/v1/projects/{world['project']}/claims",
            headers=manager,
            json={
                "statement": "142 households now collect piped water at Site A",
                "claim_type": "outcome",
            },
        )
    ).json()
    cid = claim["id"]
    await client.post(
        f"/v1/claims/{cid}/evidence",
        headers=manager,
        json={
            "asset_id": str(world["pipe"]["id"]),
            "observation_id": str(world["pipe"]["observations"]["pipe_installation"]),
        },
    )
    check = (await client.get(f"/v1/claims/{cid}", headers=manager)).json()["rule_check"]
    assert check["unsourced_numbers"] == ["142"] and not check["passed"]

    metric = (
        await client.post(
            f"/v1/projects/{world['project']}/metrics",
            headers=manager,
            json={
                "name": "Households connected",
                "value": "142",
                "unit": "households",
                "method": "Door-to-door survey",
                "source_type": "field_survey",
                "source_reference": "Form HH-7, 30 Sep 2026",
            },
        )
    ).json()
    assert (
        await client.put(f"/v1/claims/{cid}/metrics/{metric['id']}", headers=manager)
    ).status_code == 204
    detail = (await client.get(f"/v1/claims/{cid}", headers=manager)).json()
    assert detail["rule_check"]["passed"] and detail["metrics"][0]["value"] in ("142.0000", "142")

    # four-eyes: the author (even as reviewer-level manager) cannot approve their own claim
    await client.post(f"/v1/claims/{cid}/submit", headers=manager)
    await client.post(f"/v1/claims/{cid}/validate", headers=manager)
    own = await client.post(f"/v1/claims/{cid}/approve", headers=manager, json={})
    assert own.status_code == 403
    graph = (await client.get(f"/v1/claims/{cid}/graph", headers=manager)).json()
    assert "metric" in {n["type"] for n in graph["nodes"]}


async def test_activity_event_suggestions(client: httpx.AsyncClient, world: dict[str, Any]) -> None:
    reviewer = auth("r", world["org"], "reviewer")
    suggestions = (
        await client.get(f"/v1/projects/{world['project']}/events/suggestions", headers=reviewer)
    ).json()
    pipe = next(s for s in suggestions if s["activity"] == "pipe_installation")
    assert pipe["site_name"] == "Village A" and pipe["asset_ids"] == [str(world["pipe"]["id"])]
    event = await client.post(
        f"/v1/projects/{world['project']}/events",
        headers=reviewer,
        json={
            "activity": "pipe_installation",
            "title": pipe["suggested_title"],
            "site_id": world["site_a"],
            "starts_on": pipe["starts_on"],
            "ends_on": pipe["ends_on"],
            "asset_ids": pipe["asset_ids"],
        },
    )
    assert event.status_code == 201 and event.json()["evidence_count"] == 1
    listed = (await client.get(f"/v1/projects/{world['project']}/events", headers=reviewer)).json()
    assert listed[0]["title"] == "Pipe installation at Village A"


async def test_partial_word_matches_are_labelled_and_ranked_below_full_matches(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    """'a man eating apple' used to return anything mentioning 'man' as if it were a match."""
    viewer = auth("v", world["org"], "viewer")

    async def search(query: str) -> dict[str, Any]:
        response = await client.post(
            "/v1/search",
            headers=viewer,
            json={"project_id": world["project"], "query": query, "use_llm_planner": False},
        )
        assert response.status_code == 200, response.text
        return response.json()

    partial = await search("excavator eating apple")
    assert partial["query_terms"] == ["excavator", "eating", "apple"]
    assert partial["complete_matches"] == 0
    dig = next(r for r in partial["results"] if r["asset"]["id"] == str(world["dig"]["id"]))
    assert dig["missing_terms"] == ["eating", "apple"]
    assert "doesn't mention: eating, apple" in dig["reasons"]
    assert "partial text match" in dig["reasons"]

    full = await search("excavator trench")
    assert full["complete_matches"] >= 1
    first = full["results"][0]
    assert first["asset"]["id"] == str(world["dig"]["id"]) and first["missing_terms"] == []


def test_cloudinary_expression_requires_every_word() -> None:
    from evidentia_api.services.retrievers import cloudinary_expression

    expression = cloudinary_expression(uuid.UUID(int=1), [], "show a man eating apple")
    assert expression.endswith("(man AND eating AND apple)")


def test_coverage_multiplier() -> None:
    from evidentia_core.domain.ranking import coverage_multiplier

    assert coverage_multiplier(0, 3) == {}
    assert coverage_multiplier(2, 3) == {"partial_match": pytest.approx(0.5 + 0.5 / 3)}
    assert coverage_multiplier(3, 3) == {"partial_match": 0.5}
