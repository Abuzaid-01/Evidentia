"""API integration tests: real Postgres (with RLS) + Redis; Cloudinary is never contacted."""

from __future__ import annotations

import json
import time
from typing import Any

import cloudinary.utils
import httpx
import pytest
from evidentia_cloudinary.webhooks import compute_legacy_signature

pytestmark = pytest.mark.integration

SECRET = "test_secret_value"


def auth(user: str, org: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev.{user}.{org}.{role}"}


async def _project_with_site(client: httpx.AsyncClient, org: str) -> tuple[str, str]:
    manager = auth("mgr", org, "manager")
    r = await client.post(
        "/v1/projects",
        headers=manager,
        json={"name": "Community Water Access", "starts_on": "2026-04-01", "ends_on": "2026-09-30"},
    )
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]
    r = await client.post(
        f"/v1/projects/{project_id}/sites",
        headers=manager,
        json={"name": "Village A", "code": "A", "latitude": 25.75, "longitude": 71.39},
    )
    assert r.status_code == 201, r.text
    return project_id, r.json()["id"]


async def _sign(
    client: httpx.AsyncClient, org: str, project_id: str, site_id: str, **extra: Any
) -> dict[str, Any]:
    body = {
        "project_id": project_id,
        "site_id": site_id,
        "filename": "IMG_0001.JPG",
        "content_type": "image/jpeg",
        "size_bytes": 2_000_000,
        "declared_activity": "pipe_installation",
        **extra,
    }
    r = await client.post("/v1/uploads/sign", headers=auth("field", org, "contributor"), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _webhook(payload: dict[str, Any], ts: int | None = None) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    stamp = str(ts or int(time.time()))
    return body, {
        "X-Cld-Timestamp": stamp,
        "X-Cld-Signature": compute_legacy_signature(body, stamp, SECRET),
        "Content-Type": "application/json",
    }


# --- tenancy & roles -------------------------------------------------------------------------------


async def test_tenant_isolation_is_enforced(client: httpx.AsyncClient, org: str) -> None:
    project_id, _ = await _project_with_site(client, org)
    other = auth("intruder", f"{org}x", "admin")

    assert (await client.get("/v1/projects", headers=other)).json() == []
    assert (await client.get(f"/v1/projects/{project_id}", headers=other)).status_code == 404
    r = await client.post(
        f"/v1/projects/{project_id}/sites", headers=other, json={"name": "x", "code": "X"}
    )
    assert r.status_code == 404


async def test_roles_are_enforced(client: httpx.AsyncClient, org: str) -> None:
    project_id, _ = await _project_with_site(client, org)
    r = await client.post("/v1/projects", headers=auth("v", org, "viewer"), json={"name": "Nope"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    r = await client.post(
        f"/v1/projects/{project_id}/sites",
        headers=auth("c", org, "contributor"),
        json={"name": "x", "code": "Y"},
    )
    assert r.status_code == 403


async def test_missing_or_bad_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/me")).status_code == 401
    assert (await client.get("/v1/me", headers={"Authorization": "Bearer nope"})).status_code == 401


# --- upload validation ------------------------------------------------------------------------------


async def test_upload_policy_validation(client: httpx.AsyncClient, org: str) -> None:
    project_id, site_id = await _project_with_site(client, org)
    contributor = auth("field", org, "contributor")
    base = {"project_id": project_id, "site_id": site_id, "filename": "a", "size_bytes": 10}

    r = await client.post(
        "/v1/uploads/sign", headers=contributor, json={**base, "content_type": "application/pdf"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "media_rejected"
    r = await client.post(
        "/v1/uploads/sign",
        headers=contributor,
        json={**base, "content_type": "image/jpeg", "declared_activity": "rocket_launch"},
    )
    assert r.status_code == 422


# --- signed upload -> confirm -> webhook ----------------------------------------------------------------


async def test_signed_upload_confirm_and_webhook_are_idempotent(
    client: httpx.AsyncClient, org: str, enqueued: list[Any]
) -> None:
    project_id, site_id = await _project_with_site(client, org)
    signed = await _sign(client, org, project_id, site_id)
    asset_id = signed["asset_id"]
    fields = signed["fields"]

    # server-controlled parameters, covered by the signature
    assert fields["public_id"] == asset_id
    assert fields["type"] == "authenticated"
    assert fields["overwrite"] == "false"
    assert fields["asset_folder"].endswith(f"proj_{project_id}/site_{site_id}")
    unsigned = {k: v for k, v in fields.items() if k not in {"signature", "api_key"}}
    assert cloudinary.utils.api_sign_request(unsigned, SECRET) == fields["signature"]

    viewer = auth("v", org, "viewer")
    listing = await client.get(f"/v1/projects/{project_id}/assets", headers=viewer)
    assert listing.json()["items"] == []  # pending intents are hidden by default
    listing = await client.get(
        f"/v1/projects/{project_id}/assets?include_pending=true", headers=viewer
    )
    assert [a["id"] for a in listing.json()["items"]] == [asset_id]

    contributor = auth("field", org, "contributor")
    bad = await client.post(
        f"/v1/assets/{asset_id}/confirm",
        headers=contributor,
        json={"public_id": asset_id, "version": 1, "signature": "0" * 40},
    )
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_upload_signature"

    good_sig = cloudinary.utils.api_sign_request({"public_id": asset_id, "version": "1712"}, SECRET)
    confirm = {"public_id": asset_id, "version": 1712, "signature": good_sig}
    r = await client.post(f"/v1/assets/{asset_id}/confirm", headers=contributor, json=confirm)
    assert r.status_code == 200 and r.json()["state"] == "uploaded"
    r = await client.post(f"/v1/assets/{asset_id}/confirm", headers=contributor, json=confirm)
    assert r.status_code == 200
    assert enqueued == [("evidentia.pipeline.process_asset", (asset_id,))]  # exactly once

    body, headers = _webhook(
        {"notification_type": "upload", "public_id": asset_id, "asset_id": "cld1", "version": 1712}
    )
    r = await client.post("/v1/webhooks/cloudinary", content=body, headers=headers)
    assert r.json() == {"status": "processed", "outcome": "already_claimed"}
    r = await client.post("/v1/webhooks/cloudinary", content=body, headers=headers)
    assert r.json()["status"] == "duplicate"
    assert len(enqueued) == 1

    audit = await client.get("/v1/audit", headers=auth("mgr", org, "manager"))
    actions = [e["action"] for e in audit.json()]
    assert "asset.upload_signed" in actions and "asset.uploaded" in actions


async def test_webhook_first_then_confirm(
    client: httpx.AsyncClient, org: str, enqueued: list[Any]
) -> None:
    project_id, site_id = await _project_with_site(client, org)
    asset_id = (await _sign(client, org, project_id, site_id))["asset_id"]

    body, headers = _webhook(
        {"notification_type": "upload", "public_id": asset_id, "asset_id": "cld2", "version": 9}
    )
    r = await client.post("/v1/webhooks/cloudinary", content=body, headers=headers)
    assert r.json()["outcome"] == "claimed"

    sig = cloudinary.utils.api_sign_request({"public_id": asset_id, "version": "9"}, SECRET)
    r = await client.post(
        f"/v1/assets/{asset_id}/confirm",
        headers=auth("field", org, "contributor"),
        json={"public_id": asset_id, "version": 9, "signature": sig},
    )
    assert r.status_code == 200
    assert enqueued == [("evidentia.pipeline.process_asset", (asset_id,))]


async def test_webhook_signature_and_replay_protection(client: httpx.AsyncClient) -> None:
    body, headers = _webhook({"notification_type": "upload", "public_id": "x", "version": 1})
    headers["X-Cld-Signature"] = "0" * 40
    assert (
        await client.post("/v1/webhooks/cloudinary", content=body, headers=headers)
    ).status_code == 401

    body, headers = _webhook(
        {"notification_type": "upload", "public_id": "x", "version": 1},
        ts=int(time.time()) - 3 * 3600,
    )
    assert (
        await client.post("/v1/webhooks/cloudinary", content=body, headers=headers)
    ).status_code == 401


async def test_media_urls_are_signed_and_originals_expire(
    client: httpx.AsyncClient, org: str, enqueued: list[Any]
) -> None:
    project_id, site_id = await _project_with_site(client, org)
    asset_id = (await _sign(client, org, project_id, site_id))["asset_id"]
    viewer = auth("v", org, "viewer")
    assert (await client.get(f"/v1/assets/{asset_id}/media", headers=viewer)).status_code == 422

    sig = cloudinary.utils.api_sign_request({"public_id": asset_id, "version": "3"}, SECRET)
    await client.post(
        f"/v1/assets/{asset_id}/confirm",
        headers=auth("field", org, "contributor"),
        json={"public_id": asset_id, "version": 3, "signature": sig},
    )
    review = (
        await client.get(f"/v1/assets/{asset_id}/media?variant=review", headers=viewer)
    ).json()
    assert "/authenticated/s--" in review["url"] and "t_ev_review" in review["url"]
    assert review["named_transformation"] == "ev_review"
