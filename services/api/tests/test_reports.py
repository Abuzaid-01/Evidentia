"""Phase 5 integration tests: reports, citation-checked narrative, immutable snapshots, PDF.

Real Postgres (RLS + the snapshot immutability trigger) and Redis. No LLM is configured, so the
narrative uses the deterministic fallback; Cloudinary and Chromium are replaced in the PDF test.
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


def _seed_asset(
    org_id: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID, name: str
) -> dict[str, uuid.UUID]:
    """A processed image with one verified AI observation produced by a recorded analysis run."""
    from evidentia_core.db.models import AnalysisRun, Asset, Observation
    from evidentia_core.db.session import sync_system_session
    from evidentia_core.domain.enums import (
        AnalysisTask,
        AssetState,
        ObservationStatus,
        OntologyType,
        ProvenanceSource,
        ResourceType,
        RunStatus,
        SourceKind,
    )

    asset_id, run_id, obs_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with sync_system_session() as session:
        session.add(
            Asset(
                id=asset_id,
                organization_id=org_id,
                project_id=project_id,
                site_id=site_id,
                resource_type=ResourceType.IMAGE,
                public_id=f"evidentia/test/{asset_id}",
                cloudinary_version=1727000000,
                original_filename=f"{name}.jpg",
                format="jpg",
                sha256="ab" * 32,
                state=AssetState.READY,
                caption=f"{name} photo",
                capture_time=datetime(2026, 8, 12, 9, tzinfo=UTC),
                capture_time_source=ProvenanceSource.UPLOAD,
                reviewed_at=datetime.now(UTC),
            )
        )
        session.flush()
        session.add(
            AnalysisRun(
                id=run_id,
                organization_id=org_id,
                asset_id=asset_id,
                task=AnalysisTask.VISION_EXTRACT,
                provider="gemini",
                model="gemini-2.5-flash",
                prompt_version="vision-extract-2026-09-25.1",
                schema_version="1",
                taxonomy_version=1,
                run_key=uuid.uuid4().hex,
                status=RunStatus.SUCCEEDED,
            )
        )
        session.flush()
        session.add(
            Observation(
                id=obs_id,
                organization_id=org_id,
                asset_id=asset_id,
                analysis_run_id=run_id,
                ontology_type=OntologyType.ACTIVITY,
                subject="pipe_installation",
                predicate="depicted",
                confidence=0.93,
                source_kind=SourceKind.AI,
                source_provider="gemini",
                status=ObservationStatus.VERIFIED,
            )
        )
        session.commit()
    return {"asset": asset_id, "observation": obs_id}


async def _approved_claim(
    client: httpx.AsyncClient,
    w: dict[str, Any],
    statement: str,
    claim_type: str,
    metric_id: str | None = None,
) -> str:
    author, reviewer = w["author"], w["reviewer"]
    claim = (
        await client.post(
            f"/v1/projects/{w['project']}/claims",
            headers=author,
            json={"statement": statement, "claim_type": claim_type, "site_id": w["site"]},
        )
    ).json()
    cid = claim["id"]
    await client.post(
        f"/v1/claims/{cid}/evidence",
        headers=author,
        json={"asset_id": str(w["pipe"]["asset"]), "observation_id": str(w["pipe"]["observation"])},
    )
    if metric_id:
        await client.put(f"/v1/claims/{cid}/metrics/{metric_id}", headers=w["manager"])
    assert (await client.post(f"/v1/claims/{cid}/submit", headers=author)).status_code == 200
    await client.post(f"/v1/claims/{cid}/validate", headers=author)
    approved = await client.post(f"/v1/claims/{cid}/approve", headers=reviewer, json={"note": "ok"})
    assert approved.json()["status"] == "approved", approved.text
    return cid


@pytest.fixture
async def w(client: httpx.AsyncClient, org: str) -> dict[str, Any]:
    manager = auth("asha", org, "manager")
    project = (
        await client.post("/v1/projects", headers=manager, json={"name": "Community Water Access"})
    ).json()
    site = (
        await client.post(
            f"/v1/projects/{project['id']}/sites",
            headers=manager,
            json={"name": "Village A", "code": "A"},
        )
    ).json()
    org_id = uuid.UUID((await client.get("/v1/me", headers=manager)).json()["organization"]["id"])
    world: dict[str, Any] = {
        "org": org,
        "project": project["id"],
        "site": site["id"],
        "manager": manager,
        "author": auth("ravi", org, "contributor"),
        "reviewer": auth("meera", org, "reviewer"),
        "pipe": _seed_asset(org_id, uuid.UUID(project["id"]), uuid.UUID(site["id"]), "pipe"),
    }
    metric = (
        await client.post(
            f"/v1/projects/{project['id']}/metrics",
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
    world["metric"] = metric["id"]
    world["pipes_claim"] = await _approved_claim(
        client, world, "Pipes were laid in an open trench at Village A", "descriptive"
    )
    world["outcome_claim"] = await _approved_claim(
        client, world, "142 households now collect piped water", "outcome", metric["id"]
    )
    draft = await client.post(
        f"/v1/projects/{project['id']}/claims",
        headers=world["author"],
        json={"statement": "A tank was built", "claim_type": "descriptive"},
    )
    world["draft_claim"] = draft.json()["id"]
    return world


async def test_report_lifecycle_publish_verify_and_immutability(
    client: httpx.AsyncClient, w: dict[str, Any], enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    from evidentia_core import tasks

    manager, author = w["manager"], w["author"]
    created = await client.post(
        f"/v1/projects/{w['project']}/reports",
        headers=author,
        json={"title": "Q3 water report", "period_start": "2026-07-01", "period_end": "2026-09-30"},
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    # only approved claims are picked up; outcome claims come first
    assert created.json()["claim_ids"] == [w["outcome_claim"], w["pipes_claim"]]

    detail = (await client.get(f"/v1/reports/{rid}", headers=author)).json()
    assert "Generate or write the narrative before publishing" in detail["warnings"]
    assert w["draft_claim"] not in {c["id"] for c in detail["candidate_claims"]}
    assert (await client.post(f"/v1/reports/{rid}/publish", headers=manager)).status_code == 422

    # a draft claim can never be added
    bad = await client.patch(
        f"/v1/reports/{rid}", headers=author, json={"claim_ids": [w["draft_claim"]]}
    )
    assert bad.status_code == 422

    generated = (await client.post(f"/v1/reports/{rid}/generate", headers=author)).json()
    assert generated["narrative_meta"]["mode"] == "fallback"
    summary = generated["narrative"]["summary"]
    assert summary[0]["text"] == "142 households now collect piped water."
    assert summary[0]["cites"] == [{"type": "claim", "id": w["outcome_claim"]}]
    assert generated["narrative_problems"] == []

    # human edits are checked sentence by sentence
    uncited = {"summary": [{"text": "Water flows.", "cites": []}], "overview": []}
    r = await client.put(f"/v1/reports/{rid}/narrative", headers=author, json=uncited)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["problems"] == [
        "Sentence has no citation"
    ]
    wrong_number = {
        "summary": [
            {
                "text": "150 households collect water.",
                "cites": [{"type": "claim", "id": w["outcome_claim"]}],
            }
        ]
    }
    r = await client.put(f"/v1/reports/{rid}/narrative", headers=author, json=wrong_number)
    assert r.status_code == 422 and "150" in r.json()["error"]["details"][0]["problems"][0]
    edited = {
        "summary": [
            {
                "text": "142 households now collect piped water. Pipes were laid at Village A.",
                "cites": [
                    {"type": "metric", "id": w["metric"]},
                    {"type": "claim", "id": w["pipes_claim"]},
                ],
            }
        ],
        "overview": [],
    }
    r = await client.put(f"/v1/reports/{rid}/narrative", headers=author, json=edited)
    assert r.status_code == 200, r.text
    assert len(r.json()["narrative"]["summary"]) == 2  # split into sentences
    assert r.json()["narrative_meta"]["edited_by"] == "Ravi"

    preview = (await client.get(f"/v1/reports/{rid}/preview", headers=author)).json()
    assert "DRAFT PREVIEW" in preview["html"] and 'href="#M1"' in preview["html"]
    assert preview["problems"] == []

    assert (await client.post(f"/v1/reports/{rid}/publish", headers=author)).status_code == 403
    published = await client.post(f"/v1/reports/{rid}/publish", headers=manager)
    assert published.status_code == 201, published.text
    snap = published.json()
    assert snap["version"] == 1 and snap["pdf_status"] == "pending"
    assert (tasks.RENDER_REPORT_PDF, (snap["id"],)) in enqueued

    manifest = (await client.get(f"/v1/reports/{rid}/snapshots/1/manifest", headers=author)).json()
    assert [c["ref"] for c in manifest["claims"]] == ["C1", "C2"]
    assert manifest["claims"][0]["approved_by"]["name"] == "Meera"
    assert manifest["metrics"][0]["value"] == "142"
    evidence = manifest["evidence"][0]
    assert evidence["observation"]["run"]["model"] == "gemini-2.5-flash"
    asset = manifest["assets"][0]
    assert asset["figure"]["named_transformation"] == "ev_thumb" and asset["figure"]["url"]
    assert manifest["narrative"]["summary"][0]["cites"] == ["M1", "C2"]
    assert manifest["published"]["version"] == 1
    # the upload-time capture date and the visual claim both surface as cited limitations
    assert any("camera timestamp" in lim["text"] for lim in manifest["limitations"])

    verify = (await client.get(f"/v1/reports/{rid}/snapshots/1/verify", headers=author)).json()
    assert verify["identical"] is True
    html = (await client.get(f"/v1/reports/{rid}/snapshots/1/html", headers=author)).json()
    import hashlib

    assert hashlib.sha256(html["html"].encode()).hexdigest() == snap["html_sha256"]

    # the database refuses to change a published snapshot
    from evidentia_core.db.session import sync_system_session
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with sync_system_session() as session, pytest.raises(DBAPIError, match="immutable"):
        session.execute(
            text("UPDATE report_snapshots SET manifest = '{}'::jsonb WHERE id = :id"),
            {"id": snap["id"]},
        )

    # PDF not ready yet
    assert (
        await client.get(f"/v1/reports/{rid}/snapshots/1/pdf", headers=author)
    ).status_code == 409

    audit = (await client.get("/v1/audit", headers=manager)).json()
    actions = {e["action"] for e in (audit["items"] if isinstance(audit, dict) else audit)}
    assert {
        "report.created",
        "report.narrative_generated",
        "report.narrative_edited",
        "report.published",
    } <= actions


async def test_retracted_claims_block_publish_but_old_snapshots_stay(
    client: httpx.AsyncClient, w: dict[str, Any], enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    manager, author = w["manager"], w["author"]
    rid = (
        await client.post(
            f"/v1/projects/{w['project']}/reports", headers=author, json={"title": "Pilot report"}
        )
    ).json()["id"]
    await client.post(f"/v1/reports/{rid}/generate", headers=author)
    assert (await client.post(f"/v1/reports/{rid}/publish", headers=manager)).status_code == 201

    retract = await client.post(
        f"/v1/claims/{w['pipes_claim']}/retract", headers=manager, json={"note": "wrong site"}
    )
    assert retract.status_code == 200
    snapshots = (await client.get(f"/v1/reports/{rid}/snapshots", headers=author)).json()
    assert snapshots[0]["retracted_claim_ids"] == [w["pipes_claim"]]
    assert (await client.get(f"/v1/reports/{rid}/snapshots/1/verify", headers=author)).json()[
        "identical"
    ]

    blocked = await client.post(f"/v1/reports/{rid}/publish", headers=manager)
    assert blocked.status_code == 422 and w["pipes_claim"] in str(blocked.json())

    await client.patch(
        f"/v1/reports/{rid}", headers=author, json={"claim_ids": [w["outcome_claim"]]}
    )
    detail = (await client.get(f"/v1/reports/{rid}", headers=author)).json()
    assert detail["narrative_problems"]  # the pipes sentence now cites a claim outside the report
    await client.post(f"/v1/reports/{rid}/generate", headers=author)
    second = await client.post(f"/v1/reports/{rid}/publish", headers=manager)
    assert second.status_code == 201 and second.json()["version"] == 2

    # other organisations cannot see the report
    outsider = auth("x", f"other{uuid.uuid4().hex[:6]}", "manager")
    assert (await client.get(f"/v1/reports/{rid}", headers=outsider)).status_code == 404


async def test_pdf_worker_uploads_and_download_link(
    client: httpx.AsyncClient,
    w: dict[str, Any],
    enqueued: list[tuple[str, tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evidentia_worker.tasks import reports as worker

    rid = (
        await client.post(
            f"/v1/projects/{w['project']}/reports", headers=w["author"], json={"title": "PDF test"}
        )
    ).json()["id"]
    await client.post(f"/v1/reports/{rid}/generate", headers=w["author"])
    snap = (await client.post(f"/v1/reports/{rid}/publish", headers=w["manager"])).json()

    uploads: list[dict[str, Any]] = []
    monkeypatch.setattr(worker, "html_to_pdf", lambda html: b"%PDF-1.7 " + html[:40].encode())
    monkeypatch.setattr(
        worker.admin,
        "upload_authenticated_raw",
        lambda data, public_id, **kw: uploads.append({"public_id": public_id, **kw}) or {},
    )
    assert worker.render_report_pdf(snap["id"]) == "ready"
    assert uploads[0]["public_id"].endswith(f"report_{rid}_v1.pdf")
    assert worker.render_report_pdf(snap["id"]) == "ready"  # idempotent: no second upload
    assert len(uploads) == 1

    snapshots = (await client.get(f"/v1/reports/{rid}/snapshots", headers=w["author"])).json()
    assert snapshots[0]["pdf_status"] == "ready" and snapshots[0]["pdf_bytes"] > 0
    link = (await client.get(f"/v1/reports/{rid}/snapshots/1/pdf", headers=w["author"])).json()
    assert "/raw/download" in link["url"] and link["expires_at"]
    # a snapshot's PDF columns may change, its manifest may not: verification still holds
    assert (await client.get(f"/v1/reports/{rid}/snapshots/1/verify", headers=w["author"])).json()[
        "identical"
    ]
