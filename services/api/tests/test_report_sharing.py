"""A public share link shows the real report, and never leaks unredacted images or the internal record."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration


def auth(user: str, org: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev.{user}.{org}.{role}"}


def _seed_photo(*args: Any) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location(
        "demo_seed", Path(__file__).with_name("test_demo.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._seed_photo(*args)  # type: ignore[no-any-return]


async def _published(client: httpx.AsyncClient, org: str, audience: str) -> dict[str, Any]:
    manager = auth("asha", org, "manager")
    project = (
        await client.post("/v1/projects", headers=manager, json={"name": f"Share {audience}"})
    ).json()
    org_id = uuid.UUID((await client.get("/v1/me", headers=manager)).json()["organization"]["id"])
    photo = _seed_photo(org_id, uuid.UUID(project["id"]), "Workers clean an open manhole.")
    await client.post(
        f"/v1/demo/assets/{photo['id']}/claim", headers=manager, json={"claim_type": "descriptive"}
    )
    report = (
        await client.post(
            f"/v1/demo/projects/{project['id']}/report",
            headers=manager,
            json={"audience": audience},
        )
    ).json()
    link = (
        await client.post(
            f"/v1/projects/{project['id']}/share-links",
            headers=manager,
            json={
                "title": "For the donor",
                "target_type": "report",
                "target_id": report["report_id"],
            },
        )
    ).json()
    return {"report": report, "link": link}


async def test_shared_internal_report_is_a_redacted_copy(
    client: httpx.AsyncClient, org: str, enqueued: list[Any]
) -> None:
    shared = await _published(client, org, "internal")
    r = await client.get(f"/v1/share/{shared['link']['token']}")  # no Authorization header
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    html = data["html"]

    assert "manifest" not in data  # the internal record is never sent
    assert data["redacted_copy"] is True
    assert data["pdf_url"] is None  # the stored PDF is the unredacted internal one
    assert "ev_public_redacted" in html  # Cloudinary face-pixelated rendition
    assert "t_ev_thumb" not in html and "/t_ev_thumb/" not in html  # no internal renditions
    assert "/assets/" not in html and "/claims/" not in html  # no links into the app
    assert "Faces are pixelated" in html
    assert "What was verified" in html  # it is the real report, not a summary


async def test_shared_external_report_is_served_as_published(
    client: httpx.AsyncClient, org: str, enqueued: list[Any]
) -> None:
    shared = await _published(client, org, "external")
    data = (await client.get(f"/v1/share/{shared['link']['token']}")).json()["data"]
    assert data["redacted_copy"] is False
    assert (
        data["fingerprint"]
        == data["published_fingerprint"]
        == shared["report"]["snapshot"]["manifest_sha256"]
    )
    assert "ev_public_redacted" in data["html"]
