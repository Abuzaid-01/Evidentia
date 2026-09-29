"""Phase 8 integration tests: Campaign Studio, social transformations with mandatory
face redaction, generative quarantine from claims, video reel splicing, lineage tracing,
and external read-only share links.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from evidentia_core.db.models import Asset, Derivative
from evidentia_core.db.session import sync_system_session
from evidentia_core.domain.enums import AssetState, ProvenanceSource, ResourceType

pytestmark = pytest.mark.integration


def auth(user: str, org: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev.{user}.{org}.{role}"}


@pytest.fixture
async def world(client: httpx.AsyncClient, org: str) -> dict[str, Any]:
    manager = auth("asha", org, "manager")
    project = (
        await client.post(
            "/v1/projects", headers=manager, json={"name": "Water Infrastructure Campaign"}
        )
    ).json()
    site = (
        await client.post(
            f"/v1/projects/{project['id']}/sites",
            headers=manager,
            json={"name": "Site Rampura", "code": "RAM", "latitude": 13.0, "longitude": 77.0},
        )
    ).json()
    me = (await client.get("/v1/me", headers=manager)).json()

    # Create an approved ready asset
    asset_id = uuid.uuid4()
    with sync_system_session() as session:
        session.add(
            Asset(
                id=asset_id,
                organization_id=uuid.UUID(me["organization"]["id"]),
                project_id=uuid.UUID(project["id"]),
                site_id=uuid.UUID(site["id"]),
                resource_type=ResourceType.IMAGE,
                public_id=f"evidentia/test/{asset_id}",
                original_filename="trench_digging.jpg",
                format="jpg",
                width=1920,
                height=1080,
                state=AssetState.READY,
                caption="Workers excavating trench for pipeline",
                capture_time=datetime.now(UTC),
                capture_time_source=ProvenanceSource.EXIF,
                latitude=13.0,
                longitude=77.0,
                location_source=ProvenanceSource.EXIF,
            )
        )
        session.commit()

    return {
        "org": org,
        "org_id": uuid.UUID(me["organization"]["id"]),
        "project_id": project["id"],
        "site_id": site["id"],
        "asset_id": str(asset_id),
        "manager": manager,
    }


async def test_social_formats_include_mandatory_face_redaction(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    """Requirement: no externally shared output contains an unredacted face."""
    res = await client.post(
        f"/v1/projects/{world['project_id']}/campaigns",
        headers=world["manager"],
        json={
            "title": "Summer Campaign",
            "headline": "Clean Water Pipeline Completed",
            "stat_text": "2,400 People Served",
            "brand_tag": "JALSEVA FIELD",
            "asset_id": world["asset_id"],
            "formats": ["1:1", "4:5", "9:16", "16:9"],
            "redact": True,
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["title"] == "Summer Campaign"
    assert data["generative"] is False

    renditions = data["renditions"]
    assert len(renditions) == 4

    for fmt in ["1:1", "4:5", "9:16", "16:9"]:
        assert fmt in renditions
        r = renditions[fmt]
        # Mandatory redaction must be present in every single transformation
        assert "e_pixelate_faces:12" in r["transformation"]
        # Text overlays must be present
        assert "Clean%20Water%20Pipeline%20Completed" in r["transformation"]
        assert "2%2C400%20People%20Served" in r["transformation"]
        assert "JALSEVA%20FIELD" in r["transformation"]
        assert r["url"].startswith("https://res.cloudinary.com")
        assert r["generative"] is False


async def test_generative_effects_are_flagged_and_watermarked(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    """Generative effects must be watermarked and flagged as generative in lineage."""
    res = await client.post(
        f"/v1/projects/{world['project_id']}/campaigns",
        headers=world["manager"],
        json={
            "title": "Extended Visuals",
            "headline": "Community Water Station",
            "asset_id": world["asset_id"],
            "formats": ["1:1"],
            "generative_fill": True,
            "generative_restore": True,
            "redact": True,
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["generative"] is True

    r = data["renditions"]["1:1"]
    assert r["generative"] is True
    # Watermark must be included in transformation
    assert "ILLUSTRATIVE%20-%20ENHANCED%20FOR%20PRESENTATION" in r["transformation"]
    assert "b_gen_fill" in r["transformation"]
    assert "e_gen_restore" in r["transformation"]
    assert "e_pixelate_faces:12" in r["transformation"]


async def test_generative_outputs_cannot_be_attached_to_claims(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    """Enforced by test: generative outputs can NEVER be attached as evidence to claims."""
    # 1. Create a generative campaign
    res = await client.post(
        f"/v1/projects/{world['project_id']}/campaigns",
        headers=world["manager"],
        json={
            "title": "Generative Promo",
            "headline": "AI Enhanced Poster",
            "asset_id": world["asset_id"],
            "formats": ["1:1"],
            "generative_fill": True,
            "redact": True,
        },
    )
    assert res.status_code == 201

    # 2. Create a claim
    claim_res = await client.post(
        f"/v1/projects/{world['project_id']}/claims",
        headers=world["manager"],
        json={
            "statement": "The project restored water access to Village Rampura.",
            "claim_type": "progress",
        },
    )
    assert claim_res.status_code == 201
    claim_id = claim_res.json()["id"]

    # 3. Create an asset that is marked generative in flags
    gen_asset_id = uuid.uuid4()
    with sync_system_session() as session:
        session.add(
            Asset(
                id=gen_asset_id,
                organization_id=world["org_id"],
                project_id=uuid.UUID(world["project_id"]),
                resource_type=ResourceType.IMAGE,
                public_id=f"evidentia/test/{gen_asset_id}",
                original_filename="gen_poster.jpg",
                state=AssetState.READY,
                flags={"generative": True},
            )
        )
        session.commit()

    # 4. Attempt to attach the generative asset to the claim -> MUST FAIL with 422
    attach_res = await client.post(
        f"/v1/claims/{claim_id}/evidence",
        headers=world["manager"],
        json={"asset_id": str(gen_asset_id)},
    )
    assert attach_res.status_code == 422
    assert (
        "Generative or campaign-enhanced media cannot be attached to claims"
        in attach_res.json()["error"]["message"]
    )

    # 5. Also test attaching a derivative marked generative
    with sync_system_session() as session:
        deriv = Derivative(
            organization_id=world["org_id"],
            asset_id=uuid.UUID(world["asset_id"]),
            purpose="campaign_1x1",
            transformation="c_fill,w_1080,h_1080,b_gen_fill",
            generative=True,
            source="campaign_studio",
        )
        session.add(deriv)
        session.commit()
        deriv_id = str(deriv.id)

    attach_deriv_res = await client.post(
        f"/v1/claims/{claim_id}/evidence",
        headers=world["manager"],
        json={"asset_id": world["asset_id"], "derivative_id": deriv_id},
    )
    assert attach_deriv_res.status_code == 422
    assert (
        "Generative or campaign-enhanced media cannot be attached to claims"
        in attach_deriv_res.json()["error"]["message"]
    )


async def test_asset_lineage_shows_all_transformations(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    """Requirement: every campaign asset shows its lineage."""
    # Create campaign card to produce derivatives
    await client.post(
        f"/v1/projects/{world['project_id']}/campaigns",
        headers=world["manager"],
        json={
            "title": "Lineage Test",
            "headline": "Tracking Lineage",
            "asset_id": world["asset_id"],
            "formats": ["1:1", "16:9"],
            "redact": True,
        },
    )

    lineage_res = await client.get(
        f"/v1/assets/{world['asset_id']}/lineage",
        headers=world["manager"],
    )
    assert lineage_res.status_code == 200, lineage_res.text
    data = lineage_res.json()
    assert data["asset_id"] == world["asset_id"]
    assert data["original_filename"] == "trench_digging.jpg"
    assert data["public_id"].startswith("evidentia/test/")
    assert len(data["derivatives"]) >= 2

    purposes = [d["purpose"] for d in data["derivatives"]]
    assert "campaign_1x1" in purposes
    assert "campaign_16x9" in purposes

    for d in data["derivatives"]:
        assert "url" in d
        assert "transformation" in d
        assert d["transformation"] != ""


async def test_video_reel_splicing(client: httpx.AsyncClient, world: dict[str, Any]) -> None:
    """Test creating a video highlight reel stitched from cited segments with fl_splice."""
    # Create two video assets
    vid1_id = uuid.uuid4()
    vid2_id = uuid.uuid4()
    with sync_system_session() as session:
        for vid_id, name in [(vid1_id, "inspection_1.mp4"), (vid2_id, "inspection_2.mp4")]:
            session.add(
                Asset(
                    id=vid_id,
                    organization_id=world["org_id"],
                    project_id=uuid.UUID(world["project_id"]),
                    resource_type=ResourceType.VIDEO,
                    public_id=f"evidentia/test/{vid_id}",
                    original_filename=name,
                    state=AssetState.READY,
                    duration_seconds=30.0,
                )
            )
        session.commit()

    reel_res = await client.post(
        f"/v1/projects/{world['project_id']}/campaigns/video-reel",
        headers=world["manager"],
        json={
            "title": "Project Highlights",
            "segments": [
                {
                    "asset_id": str(vid1_id),
                    "start_ms": 2000,
                    "end_ms": 7000,
                    "caption": "Site preparation",
                },
                {
                    "asset_id": str(vid2_id),
                    "start_ms": 10000,
                    "end_ms": 15000,
                    "caption": "Pipe placement",
                },
            ],
            "redact": True,
        },
    )
    assert reel_res.status_code == 201, reel_res.text
    reel = reel_res.json()
    assert reel["title"] == "Project Highlights"
    assert reel["segments_count"] == 2
    assert reel["duration_seconds"] == 10.0
    assert "fl_splice" in reel["transformation"]
    assert "e_pixelate_faces:12" in reel["transformation"]


async def test_external_share_links_and_mandatory_redaction(
    client: httpx.AsyncClient, world: dict[str, Any]
) -> None:
    """External share links must be accessible publicly and guarantee face redaction & GPS stripping."""
    # 1. Create a share link for evidence
    create_res = await client.post(
        f"/v1/projects/{world['project_id']}/share-links",
        headers=world["manager"],
        json={
            "title": "Public Evidence Share",
            "target_type": "evidence",
            "target_id": world["asset_id"],
            "expires_in_days": 14,
        },
    )
    assert create_res.status_code == 201, create_res.text
    link = create_res.json()
    token = link["token"]
    assert link["view_count"] == 0

    # 2. Access the public share link without auth headers
    public_res = await client.get(f"/v1/share/{token}")
    assert public_res.status_code == 200, public_res.text
    shared = public_res.json()
    assert shared["title"] == "Public Evidence Share"
    assert shared["target_type"] == "evidence"

    # CRITICAL SECURITY CHECK: Redacted media URL ONLY
    media_url = shared["data"]["media_url"]
    assert "e_pixelate_faces:12" in media_url or "t_ev_public_redacted" in media_url

    # Precise GPS must be stripped
    assert "latitude" not in shared["data"]
    assert "longitude" not in shared["data"]

    # 3. Verify view count incremented
    list_res = await client.get(
        f"/v1/projects/{world['project_id']}/share-links",
        headers=world["manager"],
    )
    assert list_res.status_code == 200
    links = list_res.json()
    matching = next(link for link in links if link["token"] == token)
    assert matching["view_count"] == 1

    # 4. Revoke the share link
    revoke_res = await client.delete(
        f"/v1/share-links/{link['id']}",
        headers=world["manager"],
    )
    assert revoke_res.status_code == 204

    # 5. Accessing revoked link -> must return 404
    revoked_access = await client.get(f"/v1/share/{token}")
    assert revoked_access.status_code == 404
