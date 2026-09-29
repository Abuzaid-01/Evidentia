"""Analytics, pipeline health metrics, and AI cost accounting service (PLAN Phase 9)."""

from __future__ import annotations

import uuid
from collections import defaultdict

import numpy as np
from evidentia_core.db.models import AnalysisRun, Asset, Claim, Derivative, Observation
from evidentia_core.domain.enums import ObservationStatus, RunStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.schemas.analytics import (
    ActivityMetric,
    CostBreakdown,
    IngestionHealth,
    ProjectAnalyticsOut,
    VerificationHealth,
)


async def get_project_analytics(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> ProjectAnalyticsOut:
    # 1. Assets metrics
    assets = (await session.scalars(select(Asset).where(Asset.project_id == project_id))).all()
    asset_ids = [a.id for a in assets]

    state_counts: dict[str, int] = defaultdict(int)
    activity_assets: dict[str, int] = defaultdict(int)
    activity_verified: dict[str, int] = defaultdict(int)
    total_bytes = 0

    for a in assets:
        st = a.state.value if hasattr(a.state, "value") else str(a.state)
        state_counts[st] += 1
        total_bytes += a.bytes or 0
        act = a.top_activity or a.declared_activity
        if act:
            activity_assets[act] += 1
            if a.verified_activities and act in a.verified_activities:
                activity_verified[act] += 1

    total_assets = len(assets)
    failed_assets = state_counts.get("failed_permanent", 0) + state_counts.get(
        "failed_transient", 0
    )
    failure_rate = round((failed_assets / total_assets) * 100, 2) if total_assets > 0 else 0.0

    # 2. Analysis runs metrics & latency
    if asset_ids:
        runs = (
            await session.scalars(select(AnalysisRun).where(AnalysisRun.asset_id.in_(asset_ids)))
        ).all()
        derivatives_count = (
            await session.scalar(
                select(func.count(Derivative.id)).where(Derivative.asset_id.in_(asset_ids))
            )
            or 0
        )
        observations = (
            await session.scalars(select(Observation).where(Observation.asset_id.in_(asset_ids)))
        ).all()
    else:
        runs = []
        derivatives_count = 0
        observations = []

    successful_runs = sum(1 for r in runs if r.status == RunStatus.SUCCEEDED)
    failed_runs = sum(1 for r in runs if r.status == RunStatus.FAILED)
    latencies = [r.latency_ms for r in runs if r.latency_ms is not None]

    if latencies:
        avg_lat = round(float(np.mean(latencies)), 1)
        p95_lat = round(float(np.percentile(latencies, 95)), 1)
    else:
        avg_lat = 0.0
        p95_lat = 0.0

    ingestion = IngestionHealth(
        total_assets=total_assets,
        state_counts=dict(state_counts),
        failure_rate_pct=failure_rate,
        avg_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        total_analysis_runs=len(runs),
        successful_runs=successful_runs,
        failed_runs=failed_runs,
    )

    # 3. AI & Infrastructure Cost Accounting
    # Pricing benchmarks:
    # Cloudinary storage: ~$0.05 / GB-month
    # Cloudinary transformations: ~$0.001 per derivative
    # LLM tokens: ~$0.0003 per analysis run
    # SigLIP embeddings: ~$0.0001 per asset
    storage_gb = total_bytes / (1024**3)
    cld_storage_cost = round(storage_gb * 0.05, 4)
    cld_trans_cost = round(derivatives_count * 0.001, 4)
    llm_cost = round(len(runs) * 0.0004, 4)
    embedding_cost = round(total_assets * 0.0001, 4)
    total_cost = round(cld_storage_cost + cld_trans_cost + llm_cost + embedding_cost, 4)

    costs = CostBreakdown(
        cloudinary_transformations_usd=cld_trans_cost,
        cloudinary_storage_usd=cld_storage_cost,
        llm_tokens_usd=llm_cost,
        embedding_compute_usd=embedding_cost,
        total_estimated_usd=total_cost,
    )

    # 4. Verification Health
    claims = (await session.scalars(select(Claim).where(Claim.project_id == project_id))).all()
    claim_status_counts: dict[str, int] = defaultdict(int)
    for c in claims:
        st = c.status.value if hasattr(c.status, "value") else str(c.status)
        claim_status_counts[st] += 1

    total_obs = len(observations)
    verified_obs = sum(1 for o in observations if o.status == ObservationStatus.VERIFIED)
    verif_rate = round((verified_obs / total_obs) * 100, 1) if total_obs > 0 else 0.0

    verification = VerificationHealth(
        claims_total=len(claims),
        claims_by_status=dict(claim_status_counts),
        observations_total=total_obs,
        observations_verified=verified_obs,
        verification_rate_pct=verif_rate,
    )

    # 5. Activity breakdown list
    all_acts = sorted(set(activity_assets.keys()) | set(activity_verified.keys()))
    activities_list = [
        ActivityMetric(
            activity=act,
            asset_count=activity_assets[act],
            verified_count=activity_verified[act],
        )
        for act in all_acts
    ]

    return ProjectAnalyticsOut(
        project_id=project_id,
        ingestion=ingestion,
        costs=costs,
        verification=verification,
        activities=activities_list,
    )
