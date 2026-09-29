"""Integration tests for spatial-temporal map/timeline and project analytics (PLAN Phase 9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from evidentia_core.db.models import AnalysisRun, Asset, Claim, Organization
from evidentia_core.db.session import system_session
from evidentia_core.domain.enums import (
    AnalysisTask,
    AssetState,
    ClaimStatus,
    ClaimType,
    ProvenanceSource,
    ResourceType,
    RunStatus,
)
from sqlalchemy import select


def _auth(user: str, org: str, role: str = "manager") -> dict[str, str]:
    return {"Authorization": f"Bearer dev.{user}.{org}.{role}"}


@pytest.mark.asyncio
async def test_spatial_temporal_and_analytics_endpoints(client: httpx.AsyncClient) -> None:
    org = f"org_{uuid.uuid4().hex[:8]}"
    auth = _auth("manager_user", org, "manager")

    # 1. Create a project
    resp_p = await client.post(
        "/v1/projects", headers=auth, json={"name": "Water Infrastructure Project"}
    )
    assert resp_p.status_code == 201
    project_id = uuid.UUID(resp_p.json()["id"])

    # 2. Create two sites with coordinates
    resp_s1 = await client.post(
        f"/v1/projects/{project_id}/sites",
        headers=auth,
        json={"name": "Site Alpha", "code": "alpha", "latitude": 13.0827, "longitude": 80.2707},
    )
    assert resp_s1.status_code == 201
    site_1_id = uuid.UUID(resp_s1.json()["id"])

    resp_s2 = await client.post(
        f"/v1/projects/{project_id}/sites",
        headers=auth,
        json={"name": "Site Beta", "code": "beta", "latitude": 12.9716, "longitude": 77.5946},
    )
    assert resp_s2.status_code == 201
    site_2_id = uuid.UUID(resp_s2.json()["id"])

    # 3. Seed assets with coordinates and dates directly in DB
    async with system_session() as session:
        org_row = (
            await session.execute(select(Organization).where(Organization.slug == org))
        ).scalar_one()
        org_id = org_row.id

        now = datetime.now(UTC)
        asset1 = Asset(
            organization_id=org_id,
            project_id=project_id,
            site_id=site_1_id,
            resource_type=ResourceType.IMAGE,
            public_id=f"test/asset_{uuid.uuid4().hex[:8]}",
            state=AssetState.READY,
            top_activity="water_filter_installation",
            latitude=13.0827,
            longitude=80.2707,
            location_source=ProvenanceSource.EXIF,
            capture_time=now,
            bytes=1048576,
        )
        asset2 = Asset(
            organization_id=org_id,
            project_id=project_id,
            site_id=site_2_id,
            resource_type=ResourceType.IMAGE,
            public_id=f"test/asset_{uuid.uuid4().hex[:8]}",
            state=AssetState.READY,
            top_activity="borehole_drilling",
            latitude=12.9716,
            longitude=77.5946,
            location_source=ProvenanceSource.DEVICE,
            capture_time=now,
            bytes=2097152,
        )
        session.add_all([asset1, asset2])
        await session.flush()

        # Add an analysis run and claim
        run1 = AnalysisRun(
            organization_id=org_id,
            asset_id=asset1.id,
            task=AnalysisTask.VISION_EXTRACT,
            provider="gemini",
            model="gemini-1.5-flash",
            run_key=f"run_{uuid.uuid4().hex[:8]}",
            status=RunStatus.SUCCEEDED,
            latency_ms=450,
        )
        claim1 = Claim(
            organization_id=org_id,
            project_id=project_id,
            claim_type=ClaimType.OUTCOME,
            statement="Water purification system installed",
            status=ClaimStatus.APPROVED,
        )
        session.add_all([run1, claim1])
        await session.commit()

    # 4. Test GET /v1/projects/{project_id}/spatial-temporal
    resp_map = await client.get(f"/v1/projects/{project_id}/spatial-temporal", headers=auth)
    assert resp_map.status_code == 200
    map_data = resp_map.json()
    assert map_data["total_geotagged"] == 2
    assert len(map_data["points"]) == 2
    assert len(map_data["sites"]) == 2
    assert len(map_data["timeline"]) >= 1
    assert map_data["bounds"]["min_lat"] is not None
    assert map_data["bounds"]["max_lat"] is not None

    # 5. Test GET /v1/projects/{project_id}/analytics
    resp_analytics = await client.get(f"/v1/projects/{project_id}/analytics", headers=auth)
    assert resp_analytics.status_code == 200
    analytics_data = resp_analytics.json()
    assert analytics_data["ingestion"]["total_assets"] == 2
    assert analytics_data["ingestion"]["failure_rate_pct"] == 0.0
    assert analytics_data["ingestion"]["avg_latency_ms"] == 450.0
    assert analytics_data["costs"]["total_estimated_usd"] >= 0.0
    assert analytics_data["verification"]["claims_total"] == 1
    assert len(analytics_data["activities"]) >= 2
