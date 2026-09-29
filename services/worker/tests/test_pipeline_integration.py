"""End-to-end pipeline test on a real database: Cloudinary Admin API and model calls are faked."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

import httpx
import pytest
import redis

pytestmark = pytest.mark.integration


@pytest.fixture
def ctx(migrated_db: str) -> Iterator[Any]:
    from evidentia_ai.providers.mock import MockVisionProvider
    from evidentia_cloudinary import CloudinaryCredentials, configure
    from evidentia_core.config import get_settings
    from evidentia_core.events import EventPublisher
    from evidentia_worker.context import WorkerContext

    settings = get_settings()
    creds = CloudinaryCredentials("evidentia-test", "111122223333", "test_secret_value")
    configure(creds)
    # every rendition download returns the same fake JPEG bytes
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"\xff\xd8jpeg"))
    )
    yield WorkerContext(
        settings=settings,
        creds=creds,
        analyze=None,
        providers=[MockVisionProvider()],
        publisher=EventPublisher(settings.redis_url),
        http=http,
        redis=redis.Redis.from_url(settings.redis_url),
    )
    http.close()


def _resource(asset_id: uuid.UUID, phash: str = "ffff0000ffff0000") -> dict[str, Any]:
    return {
        "asset_id": f"cld-{asset_id.hex[:12]}",
        "version": 1712,
        "format": "jpg",
        "bytes": 245_000,
        "width": 4032,
        "height": 3024,
        "created_at": "2026-08-13T06:00:00Z",
        "etag": "abc",
        "phash": phash,
        "image_metadata": {
            "DateTimeOriginal": "2026:08:12 11:42:05",
            "OffsetTimeOriginal": "+05:30",
            "GPSLatitude": "25 deg 45' 0.00\" N",
            "GPSLongitude": "71 deg 23' 24.00\" E",
            "Make": "Google",
        },
    }


@pytest.fixture
def seeded() -> dict[str, Any]:
    from evidentia_core.db.models import Organization, Project, Site, Taxonomy
    from evidentia_core.db.session import sync_system_session
    from evidentia_core.domain.taxonomy import preset

    with sync_system_session() as session:
        org = Organization(external_id=f"test_{uuid.uuid4().hex}", name="JalSeva")
        session.add(org)
        session.flush()
        project = Project(
            organization_id=org.id,
            name="Community Water Access",
            taxonomy_preset="water_infrastructure",
            starts_on=date(2026, 4, 1),
            ends_on=date(2026, 9, 30),
        )
        session.add(project)
        session.flush()
        site = Site(
            organization_id=org.id,
            project_id=project.id,
            name="Village A",
            code="A",
            latitude=25.75,
            longitude=71.39,
            radius_m=1000,
        )
        session.add(site)
        session.add(
            Taxonomy(
                organization_id=org.id,
                project_id=project.id,
                version=1,
                activities=[a.model_dump() for a in preset("water_infrastructure").activities],
            )
        )
        session.commit()
        return {"org": org.id, "project": project.id, "site": site.id}


def _new_uploaded_asset(
    seeded: dict[str, Any], declared: str | None = "pipe_installation"
) -> uuid.UUID:
    from evidentia_core.db.models import Asset
    from evidentia_core.db.session import sync_system_session
    from evidentia_core.domain.enums import AssetState, ResourceType

    asset_id = uuid.uuid4()
    with sync_system_session() as session:
        session.add(
            Asset(
                id=asset_id,
                organization_id=seeded["org"],
                project_id=seeded["project"],
                site_id=seeded["site"],
                resource_type=ResourceType.IMAGE,
                public_id=str(asset_id),
                declared_activity=declared,
                original_filename="IMG_0001.JPG",
                state=AssetState.UPLOADED,
            )
        )
        session.commit()
    return asset_id


@pytest.fixture
def fake_cloudinary(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import evidentia_worker.pipeline.provenance as provenance
    import evidentia_worker.pipeline.register as register

    state: dict[str, Any] = {"phash": "ffff0000ffff0000", "sha": "ab" * 32}
    monkeypatch.setattr(
        register,
        "fetch_resource",
        lambda public_id, rt: _resource(uuid.UUID(public_id), state["phash"]),
    )
    monkeypatch.setattr(provenance, "_sha256_of_original", lambda asset, ctx: state["sha"])
    return state


def _load(asset_id: uuid.UUID) -> dict[str, Any]:
    from evidentia_core.db.models import AnalysisRun, Asset, Derivative, Job, Observation
    from evidentia_core.db.session import sync_system_session
    from sqlalchemy import select

    with sync_system_session() as session:
        asset = session.get(Asset, asset_id)
        return {
            "asset": asset,
            "observations": list(
                session.scalars(select(Observation).where(Observation.asset_id == asset_id))
            ),
            "runs": list(
                session.scalars(select(AnalysisRun).where(AnalysisRun.asset_id == asset_id))
            ),
            "derivatives": list(
                session.scalars(select(Derivative).where(Derivative.asset_id == asset_id))
            ),
            "jobs": list(session.scalars(select(Job).where(Job.target_id == asset_id))),
        }


def test_full_pipeline_produces_traceable_observations(
    ctx: Any, seeded: dict[str, Any], fake_cloudinary: Any
) -> None:
    from evidentia_core.domain.enums import AssetState, JobState, ProvenanceSource, RunStatus
    from evidentia_worker.pipeline.orchestrator import run_pipeline

    asset_id = _new_uploaded_asset(seeded)
    final = run_pipeline(asset_id, ctx)
    assert final in {AssetState.READY, AssetState.REVIEW_REQUIRED}

    data = _load(asset_id)
    asset = data["asset"]
    assert asset.cloudinary_asset_id and asset.format == "jpg" and asset.width == 4032
    assert asset.capture_time_source == ProvenanceSource.EXIF
    assert asset.location_source == ProvenanceSource.EXIF
    assert asset.sha256 == "ab" * 32 and asset.phash is not None
    assert "geo_outside_site_m" not in (asset.flags or {})  # EXIF GPS is inside Village A
    assert asset.caption and asset.caption.startswith("[mock]")
    assert asset.top_activity == "pipe_installation"  # declared + corroborated

    run = next(r for r in data["runs"] if r.task.value == "vision_extract")
    assert run.status == RunStatus.SUCCEEDED and run.provider == "mock" and run.prompt_version
    assert all(o.analysis_run_id == run.id for o in data["observations"])
    assert {o.source_provider for o in data["observations"]} == {"mock"}
    activity = next(o for o in data["observations"] if o.ontology_type.value == "activity")
    assert activity.review_signals and "field_team" in activity.review_signals["corroborated_by"]

    ai_rendition = next(d for d in data["derivatives"] if d.purpose == "ai")
    assert ai_rendition.named_transformation == "ev_ai"  # lineage: exactly what the model saw
    assert data["jobs"][0].state == JobState.SUCCEEDED

    # Running again is a no-op: no duplicate analysis runs or observations.
    before = (len(data["runs"]), len(data["observations"]))
    assert run_pipeline(asset_id, ctx) == final
    again = _load(asset_id)
    assert (len(again["runs"]), len(again["observations"])) == before


def test_reanalysis_creates_new_generation_and_keeps_history(
    ctx: Any, seeded: dict[str, Any], fake_cloudinary: Any
) -> None:
    from evidentia_core.domain.enums import ObservationStatus
    from evidentia_worker.pipeline.orchestrator import prepare_reanalysis, run_pipeline

    asset_id = _new_uploaded_asset(seeded)
    run_pipeline(asset_id, ctx)
    first = len(_load(asset_id)["observations"])

    assert prepare_reanalysis(asset_id, ctx)
    run_pipeline(asset_id, ctx)
    data = _load(asset_id)
    assert data["asset"].analysis_generation == 2
    superseded = [o for o in data["observations"] if o.status == ObservationStatus.SUPERSEDED]
    current = [o for o in data["observations"] if o.generation == 2]
    assert len(superseded) == first and len(current) == first


def test_duplicates_are_flagged_for_review(
    ctx: Any, seeded: dict[str, Any], fake_cloudinary: Any
) -> None:
    from evidentia_core.domain.enums import AssetState
    from evidentia_worker.pipeline.orchestrator import run_pipeline

    original = _new_uploaded_asset(seeded)
    run_pipeline(original, ctx)
    copy = _new_uploaded_asset(seeded)
    assert run_pipeline(copy, ctx) == AssetState.REVIEW_REQUIRED

    asset = _load(copy)["asset"]
    assert asset.exact_duplicate_of_id == original
    assert any("Exact duplicate" in r for r in asset.review_reasons)


def test_missing_cloudinary_asset_fails_permanently(
    ctx: Any, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import evidentia_worker.pipeline.register as register
    from evidentia_cloudinary.errors import CloudinaryNotFound
    from evidentia_core.domain.enums import AssetState
    from evidentia_worker.errors import PermanentError
    from evidentia_worker.pipeline.orchestrator import mark_permanent, run_pipeline

    def missing(*_: Any) -> Any:
        raise CloudinaryNotFound("gone")

    monkeypatch.setattr(register, "fetch_resource", missing)
    asset_id = _new_uploaded_asset(seeded)
    with pytest.raises(PermanentError):
        run_pipeline(asset_id, ctx)
    mark_permanent(asset_id, ctx, "gone")
    assert _load(asset_id)["asset"].state == AssetState.FAILED_PERMANENT


def test_rls_blocks_cross_tenant_reads(seeded: dict[str, Any]) -> None:
    from evidentia_core.db.models import Project
    from evidentia_core.db.session import set_session_tenant, sync_system_session
    from sqlalchemy import select

    with sync_system_session() as session:
        set_session_tenant(session, uuid.uuid4())  # some other organization
        assert session.scalars(select(Project).where(Project.id == seeded["project"])).all() == []
        set_session_tenant(session, seeded["org"])
        session.commit()  # start a new transaction with the new tenant context
        assert (
            len(session.scalars(select(Project).where(Project.id == seeded["project"])).all()) == 1
        )


def test_pipeline_indexes_search_document_and_embeddings(
    ctx: Any, seeded: dict[str, Any], fake_cloudinary: Any
) -> None:
    from evidentia_core.db.models import Asset, Embedding
    from evidentia_core.db.session import sync_system_session
    from evidentia_worker.pipeline.indexing import index_asset
    from evidentia_worker.pipeline.orchestrator import run_pipeline
    from sqlalchemy import func, select

    asset_id = _new_uploaded_asset(seeded)
    run_pipeline(asset_id, ctx)
    with sync_system_session() as session:
        asset = session.get(Asset, asset_id)
        assert asset.search_text and "Pipe installation" in asset.search_text
        assert asset.flags["embeddings"] == "hash-embedder-v1"
        kinds = set(session.scalars(select(Embedding.kind).where(Embedding.asset_id == asset_id)))
        assert {k.value for k in kinds} == {"image", "text"}
        # the generated tsvector is queryable
        hit = session.scalar(
            select(func.count())
            .select_from(Asset)
            .where(
                Asset.id == asset_id, Asset.search_tsv.op("@@")(func.to_tsquery("english", "pipe"))
            )
        )
        assert hit == 1
        # re-indexing unchanged content is a no-op (no duplicate rows)
        index_asset(session, asset, ctx, image=b"\xff\xd8jpeg")
        session.commit()
        assert (
            session.scalar(
                select(func.count()).select_from(Embedding).where(Embedding.asset_id == asset_id)
            )
            == 2
        )
