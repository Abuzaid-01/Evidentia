"""Deleting a project removes everything in it (despite RESTRICT evidence links), queues its
Cloudinary files for deletion, is audited, and never touches other projects or organisations."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration


def auth(user: str, org: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev.{user}.{org}.{role}"}


async def _full_project(
    client: httpx.AsyncClient, manager: dict[str, str], name: str
) -> dict[str, Any]:
    """Project with a photo, an approved claim (evidence + metric), a published report and a site."""
    import importlib.util
    from pathlib import Path

    # same seeding as the demo tests (pytest runs in importlib mode: load the module by path)
    spec = importlib.util.spec_from_file_location(
        "demo_seed", Path(__file__).with_name("test_demo.py")
    )
    assert spec and spec.loader
    demo_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo_module)
    _seed_photo = demo_module._seed_photo

    project = (await client.post("/v1/projects", headers=manager, json={"name": name})).json()
    await client.post(
        f"/v1/projects/{project['id']}/sites", headers=manager, json={"name": "Site A", "code": "A"}
    )
    org_id = uuid.UUID((await client.get("/v1/me", headers=manager)).json()["organization"]["id"])
    photo = _seed_photo(org_id, uuid.UUID(project["id"]), "Workers clean an open manhole.")
    metric = (
        await client.post(
            f"/v1/projects/{project['id']}/metrics",
            headers=manager,
            json={
                "name": "Manholes cleaned",
                "value": "4",
                "method": "count",
                "source_type": "operational_record",
                "source_reference": "sheet",
            },
        )
    ).json()
    claim = (
        await client.post(
            f"/v1/demo/assets/{photo['id']}/claim",
            headers=manager,
            json={"claim_type": "descriptive", "metric_ids": [metric["id"]]},
        )
    ).json()
    assert claim["approved"], claim
    report = (
        await client.post(f"/v1/demo/projects/{project['id']}/report", headers=manager, json={})
    ).json()
    return {"project": project, "photo": photo, "claim": claim["claim"], "report": report}


async def test_delete_project_removes_everything_and_queues_cloudinary_files(
    client: httpx.AsyncClient,
    org: str,
    enqueued: list[tuple[str, tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evidentia_core import tasks
    from evidentia_core.db.models import (
        Asset,
        Claim,
        EvidenceLink,
        Observation,
        Project,
        Report,
        ReportSnapshot,
    )
    from evidentia_core.db.session import sync_system_session
    from sqlalchemy import func, select

    manager = auth("asha", org, "manager")
    doomed = await _full_project(client, manager, "Doomed project")
    keeper = await _full_project(client, manager, "Keeper project")
    pid = doomed["project"]["id"]

    # the published snapshot has a PDF in Cloudinary: it must be deleted too
    with sync_system_session() as session:
        snap = session.scalar(
            select(ReportSnapshot).where(
                ReportSnapshot.report_id == uuid.UUID(doomed["report"]["report_id"])
            )
        )
        snap.pdf_public_id = f"evidentia/reports/report_{pid}_v1.pdf"
        session.commit()

    contributor = auth("ravi", org, "contributor")
    assert (
        await client.delete(
            f"/v1/projects/{pid}", headers=contributor, params={"confirm_name": "Doomed project"}
        )
    ).status_code == 403
    wrong = await client.delete(
        f"/v1/projects/{pid}", headers=manager, params={"confirm_name": "doomed"}
    )
    assert wrong.status_code == 422
    outsider = auth("kiran", f"x{uuid.uuid4().hex[:6]}", "admin")
    assert (
        await client.delete(
            f"/v1/projects/{pid}", headers=outsider, params={"confirm_name": "Doomed project"}
        )
    ).status_code == 404

    r = await client.delete(
        f"/v1/projects/{pid}", headers=manager, params={"confirm_name": "Doomed project"}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["assets"], out["claims"], out["reports"]) == (1, 1, 1)
    assert out["cloudinary_files_queued"] == 2  # the photo + the report PDF

    queued = [
        json.loads(args[0]) for name, args in enqueued if name == tasks.DELETE_CLOUDINARY_MEDIA
    ]
    files = {rt: ids for q in queued for rt, ids in q.items()}
    assert files["image"] == [f"evidentia/test/{doomed['photo']['id']}"]
    assert files["raw"] == [f"evidentia/reports/report_{pid}_v1.pdf"]

    assert (await client.get(f"/v1/projects/{pid}", headers=manager)).status_code == 404
    projects = [p["name"] for p in (await client.get("/v1/projects", headers=manager)).json()]
    assert "Keeper project" in projects and "Doomed project" not in projects

    with sync_system_session() as session:
        doomed_id, keeper_id = uuid.UUID(pid), uuid.UUID(keeper["project"]["id"])
        assert session.get(Project, doomed_id) is None
        for model in (Asset, Claim, Report):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.project_id == doomed_id)
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.project_id == keeper_id)
                )
                == 1
            )
        assert session.get(Observation, doomed["photo"]["observations"]["condition"]) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(EvidenceLink)
                .where(EvidenceLink.claim_id == uuid.UUID(keeper["claim"]["id"]))
            )
            >= 1
        )

    audit = (await client.get("/v1/audit", headers=manager)).json()
    events = audit["items"] if isinstance(audit, dict) else audit
    deleted = [e for e in events if e["action"] == "project.deleted"]
    assert deleted and deleted[0]["data"]["name"] == "Doomed project"


def test_delete_media_task_batches_and_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    from evidentia_worker.tasks import cloudinary_sync as worker

    calls: list[tuple[int, str]] = []

    def fake_delete(ids: list[str], resource_type: str) -> dict[str, str]:
        calls.append((len(ids), resource_type))
        return {i: "deleted" for i in ids}

    monkeypatch.setattr(worker.admin, "delete_authenticated", fake_delete)
    result = worker.delete_media(
        json.dumps({"image": [f"p{i}" for i in range(250)], "raw": ["r.pdf"]})
    )
    assert calls == [(100, "image"), (100, "image"), (50, "image"), (1, "raw")]
    assert result == {"deleted": 251}
