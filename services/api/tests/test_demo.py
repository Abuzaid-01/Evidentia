"""Demo mode: one-click claim and report, with every rule of the full workflow still enforced."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration


def auth(user: str, org: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev.{user}.{org}.{role}"}


def _seed_photo(org_id: uuid.UUID, project_id: uuid.UUID, caption: str) -> dict[str, Any]:
    """A processed photo whose AI observations are still unreviewed (PROPOSED)."""
    from evidentia_core.db.models import Asset, Observation
    from evidentia_core.db.session import sync_system_session
    from evidentia_core.domain.enums import (
        AssetState,
        ObservationStatus,
        OntologyType,
        ProvenanceSource,
        ResourceType,
        SourceKind,
    )

    asset_id = uuid.uuid4()
    obs = {
        "condition": (OntologyType.CONDITION, "manhole", "being_cleaned", 0.9),
        "object": (OntologyType.OBJECT, "shovel", "visible", 0.95),
        "other": (OntologyType.ACTIVITY, "other", "depicted", 0.95),
        "quality": (OntologyType.QUALITY, "image", "issue", None),
    }
    with sync_system_session() as session:
        session.add(
            Asset(
                id=asset_id,
                organization_id=org_id,
                project_id=project_id,
                resource_type=ResourceType.IMAGE,
                public_id=f"evidentia/test/{asset_id}",
                original_filename="manhole.jpg",
                format="jpg",
                state=AssetState.REVIEW_REQUIRED,
                caption=caption,
                capture_time=datetime(2026, 9, 20, 9, tzinfo=UTC),
                capture_time_source=ProvenanceSource.EXIF,
            )
        )
        session.flush()
        ids = {}
        for key, (kind, subject, predicate, conf) in obs.items():
            row = Observation(
                organization_id=org_id,
                asset_id=asset_id,
                ontology_type=kind,
                subject=subject,
                predicate=predicate,
                confidence=conf,
                source_kind=SourceKind.AI,
                source_provider="gemini",
                status=ObservationStatus.PROPOSED,
            )
            session.add(row)
            session.flush()
            ids[key] = row.id
        session.commit()
    return {"id": asset_id, "observations": ids}


@pytest.fixture
async def demo(client: httpx.AsyncClient, org: str) -> dict[str, Any]:
    manager = auth("asha", org, "manager")
    project = (await client.post("/v1/projects", headers=manager, json={"name": "Demo"})).json()
    org_id = uuid.UUID((await client.get("/v1/me", headers=manager)).json()["organization"]["id"])
    pid = uuid.UUID(project["id"])
    return {
        "org": org,
        "project": project["id"],
        "manager": manager,
        "photo": _seed_photo(org_id, pid, "A man is cleaning an open manhole with a shovel."),
        "numbered": _seed_photo(org_id, pid, "2 workers clean 3 manholes on the street."),
    }


async def test_one_click_claim_keeps_four_eyes_and_audit(
    client: httpx.AsyncClient, demo: dict[str, Any], enqueued: list[Any]
) -> None:
    r = await client.post(
        f"/v1/demo/assets/{demo['photo']['id']}/claim", headers=demo["manager"], json={}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    claim = out["claim"]
    assert out["approved"] and claim["status"] == "approved"
    assert claim["statement"] == "A man is cleaning an open manhole with a shovel."
    assert out["reviewed_observations"] == 3  # condition, object, activity; not the quality flag
    assert claim["decided_by_id"] != claim["created_by_id"]  # a second person approved
    assert claim["decision_note"] == "Approved in demo mode by Demo reviewer"
    # evidence: the verified condition + object, never the vague "other" activity
    linked = {e["observation_id"] for e in claim["evidence"]}
    obs = demo["photo"]["observations"]
    assert linked == {str(obs["condition"]), str(obs["object"])}
    assert all(e["verified"] for e in claim["evidence"])

    asset = (await client.get(f"/v1/assets/{demo['photo']['id']}", headers=demo["manager"])).json()
    assert asset["state"] == "ready"
    audit = (await client.get("/v1/audit", headers=demo["manager"])).json()
    actions = [e["action"] for e in (audit["items"] if isinstance(audit, dict) else audit)]
    assert {"observation.approve", "claim.created", "claim.validated", "claim.approved"} <= set(
        actions
    )


async def test_numbers_in_the_caption_are_not_claimed_without_a_metric(
    client: httpx.AsyncClient, demo: dict[str, Any], enqueued: list[Any]
) -> None:
    r = await client.post(
        f"/v1/demo/assets/{demo['numbered']['id']}/claim", headers=demo["manager"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["claim"]["statement"] == "workers clean manholes on the street."
    assert r.json()["approved"]


async def test_one_click_report_publishes_with_pdf_queued(
    client: httpx.AsyncClient, demo: dict[str, Any], enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    from evidentia_core import tasks

    empty = await client.post(
        f"/v1/demo/projects/{demo['project']}/report", headers=demo["manager"]
    )
    assert empty.status_code == 422  # nothing approved yet

    await client.post(f"/v1/demo/assets/{demo['photo']['id']}/claim", headers=demo["manager"])
    r = await client.post(
        f"/v1/demo/projects/{demo['project']}/report",
        headers=demo["manager"],
        json={"title": "Demo report"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["claims"] == 1 and out["sentences"] >= 1 and out["snapshot"]["version"] == 1
    assert (tasks.RENDER_REPORT_PDF, (out["snapshot"]["id"],)) in enqueued
    verify = await client.get(
        f"/v1/reports/{out['report_id']}/snapshots/1/verify", headers=demo["manager"]
    )
    assert verify.json()["identical"]


async def test_fast_track_existing_claim_and_roles(
    client: httpx.AsyncClient, demo: dict[str, Any], enqueued: list[Any]
) -> None:
    manager = demo["manager"]
    # a human reviewer verifies first, then someone writes a claim by hand
    obs = demo["photo"]["observations"]
    await client.post(
        f"/v1/assets/{demo['photo']['id']}/review",
        headers=auth("meera", demo["org"], "reviewer"),
        json={"decisions": [{"observation_id": str(obs["condition"]), "decision": "approve"}]},
    )
    claim = (
        await client.post(
            f"/v1/projects/{demo['project']}/claims",
            headers=manager,
            json={"statement": "The manhole was cleaned", "claim_type": "descriptive"},
        )
    ).json()
    await client.post(
        f"/v1/claims/{claim['id']}/evidence",
        headers=manager,
        json={"asset_id": str(demo["photo"]["id"]), "observation_id": str(obs["condition"])},
    )
    viewer = auth("donor", demo["org"], "viewer")
    assert (
        await client.post(f"/v1/demo/claims/{claim['id']}/approve", headers=viewer)
    ).status_code == 403
    r = await client.post(f"/v1/demo/claims/{claim['id']}/approve", headers=manager)
    assert r.status_code == 200, r.text
    assert r.json()["approved"] and r.json()["claim"]["status"] == "approved"
    again = await client.post(f"/v1/demo/claims/{claim['id']}/approve", headers=manager)
    assert again.status_code == 422


async def test_demo_mode_can_be_switched_off(
    client: httpx.AsyncClient, demo: dict[str, Any]
) -> None:
    from evidentia_core.config import get_settings

    app = client._transport.app  # type: ignore[attr-defined]
    off = get_settings().model_copy(update={"demo_mode_enabled": False})
    app.dependency_overrides[get_settings] = lambda: off
    try:
        r = await client.post(
            f"/v1/demo/assets/{demo['photo']['id']}/claim", headers=demo["manager"]
        )
        assert r.status_code == 503
        me = (await client.get("/v1/me", headers=demo["manager"])).json()
        assert me["features"]["demo_mode"] is False
    finally:
        app.dependency_overrides.clear()
