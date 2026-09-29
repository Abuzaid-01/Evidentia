"""The load benchmark measures the real API + database and cleans up after itself (PLAN Phase 9)."""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration


async def test_benchmark_measures_search_and_removes_its_data(client: httpx.AsyncClient) -> None:
    from evidentia_api.benchmark import format_report, run_benchmark
    from evidentia_core.config import get_settings
    from evidentia_core.db.models import Asset, Organization
    from evidentia_core.db.session import sync_system_session
    from sqlalchemy import func, select

    transport = client._transport
    app = transport.app  # type: ignore[attr-defined]
    with sync_system_session() as session:
        before = session.scalar(select(func.count()).select_from(Asset))

    result = await run_benchmark(
        client,
        get_settings(),
        app.state.embedder,
        assets=40,
        sites=2,
        requests=20,
        concurrency=4,
    )
    assert result.search_errors == 0
    assert len(result.search.samples_ms) == 20 and result.search.pct(95) > 0
    assert result.mean_results > 0  # the seeded corpus is actually searched
    assert result.seed_seconds > 0 and result.embed_seconds >= 0

    report = format_report(result, get_settings())
    assert "measured locally" in report and "Not measured here" in report
    assert "$" not in report  # no invented prices

    with sync_system_session() as session:
        assert session.scalar(select(func.count()).select_from(Asset)) == before
        assert (
            session.scalar(
                select(func.count())
                .select_from(Organization)
                .where(Organization.external_id.like("dev_org_loadtest%"))
            )
            == 0
        )
