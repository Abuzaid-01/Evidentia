"""Local load benchmark: measured numbers only (PLAN Phase 9).

What it measures, against the real API app and the real database:
  * registration: writing N processed assets (asset row + observation + text and image embeddings
    from the configured embedder) into Postgres, i.e. the database side of ingestion
  * search: concurrent POST /v1/search over that corpus (planner, full-text, pgvector, filters,
    fusion), timed end to end in-process

What it does NOT measure (reported as such): Cloudinary upload/transformations, Cloudinary Analyze,
LLM/VLM calls and network latency. Those cost quota and depend on the account; the report lists how
many of each one asset consumes instead of inventing prices or timings.

Everything is created in a throwaway organisation that is deleted at the end.
"""

from __future__ import annotations

import asyncio
import random
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx
from evidentia_core.config import Settings
from evidentia_core.db.models import Asset, Embedding, Observation, Organization, User
from evidentia_core.db.session import sync_system_session
from evidentia_core.domain.enums import (
    AssetState,
    EmbeddingKind,
    ObservationStatus,
    OntologyType,
    ProvenanceSource,
    ResourceType,
    SourceKind,
)
from evidentia_core.domain.search_doc import ObservationText, build_search_text
from evidentia_ml.embeddings import Embedder
from sqlalchemy import delete, select

# PLAN Phase 3 "Done when": p95 latency < 1.5 s on the demo dataset
SEARCH_P95_TARGET_MS = 1500.0

_SCENES: dict[str, list[str]] = {
    "baseline_condition": [
        "dry open field before works",
        "old hand pump with a queue",
        "bare plot",
    ],
    "excavation": [
        "excavator digging a trench",
        "workers dig a long trench",
        "soil piled by a pit",
    ],
    "pipe_installation": [
        "blue pipe lowered into a trench",
        "workers joining pvc pipes",
        "pipes laid",
    ],
    "tank_construction": [
        "concrete water tank with scaffolding",
        "tank walls being cast",
        "steel rebar",
    ],
    "community_use": [
        "women collecting water at a tap",
        "children at a new standpipe",
        "queue at tap",
    ],
}
QUERIES = [
    "pipe installation at Site A in August",
    "excavator digging a trench",
    "water tank under construction",
    "people collecting water from a tap",
    "before works, dry field",
    "verified pipe laying",
    "children at the standpipe in September",
    "concrete tank with scaffolding at Site B",
    "trench digging in July",
    "blue pipes",
    "tank construction progress",
    "community using the new tap",
    "baseline condition photos",
    "workers joining pipes",
    "water access after completion",
]


@dataclass
class Timings:
    samples_ms: list[float] = field(default_factory=list)

    def pct(self, q: float) -> float:
        if not self.samples_ms:
            return 0.0
        ordered = sorted(self.samples_ms)
        return ordered[min(len(ordered) - 1, round(q / 100 * (len(ordered) - 1)))]


@dataclass
class BenchmarkResult:
    assets: int
    sites: int
    embedder: str
    seed_seconds: float
    embed_seconds: float
    search_requests: int
    search_concurrency: int
    search_errors: int
    search_seconds: float
    search: Timings
    server_took: Timings
    mean_results: float
    llm_planner: bool
    cloudinary_search: bool
    started_at: str

    @property
    def seed_rate(self) -> float:
        return self.assets / self.seed_seconds if self.seed_seconds else 0.0

    @property
    def qps(self) -> float:
        return self.search_requests / self.search_seconds if self.search_seconds else 0.0

    @property
    def search_ok(self) -> bool:
        return self.search_errors == 0 and self.search.pct(95) < SEARCH_P95_TARGET_MS


def _embed_all(embedder: Embedder, texts: list[str], batch: int = 64) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        out.extend(embedder.embed_texts(texts[i : i + batch]))
    return out


def seed_corpus(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    site_ids: list[uuid.UUID],
    n: int,
    embedder: Embedder,
    *,
    rng: random.Random,
) -> tuple[float, float]:
    """Insert n processed assets. Returns (embedding seconds, database seconds)."""
    activities = list(_SCENES)
    start_date = datetime(2026, 6, 1, 8, tzinfo=UTC)
    specs = []
    for i in range(n):
        activity = activities[i % len(activities)]
        caption = rng.choice(_SCENES[activity])
        status = ObservationStatus.VERIFIED if rng.random() < 0.4 else ObservationStatus.PROPOSED
        text = build_search_text(
            caption=caption,
            observations=[
                ObservationText("activity", activity, "depicted", status.value, None, 0.85)
            ],
            activity_labels={a: a.replace("_", " ") for a in activities},
            site_name=None,
            filename=None,
            note=None,
        )
        specs.append((activity, caption, status, text, i))

    t0 = time.perf_counter()
    text_vecs = _embed_all(embedder, [s[3] for s in specs])
    image_vecs = _embed_all(embedder, [s[1] for s in specs])  # SigLIP shares one text/image space
    embed_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    with sync_system_session() as session:
        for (activity, caption, status, text, i), tv, iv in zip(
            specs, text_vecs, image_vecs, strict=True
        ):
            asset_id = uuid.uuid4()
            session.add(
                Asset(
                    id=asset_id,
                    organization_id=org_id,
                    project_id=project_id,
                    site_id=site_ids[i % len(site_ids)],
                    resource_type=ResourceType.IMAGE,
                    public_id=f"loadtest/{asset_id}",
                    original_filename=f"IMG_{i:05d}.jpg",
                    format="jpg",
                    state=AssetState.READY,
                    caption=caption,
                    capture_time=start_date + timedelta(hours=i * 2),
                    capture_time_source=ProvenanceSource.EXIF,
                    search_text=text,
                    top_activity=activity,
                    verified_activities=[activity]
                    if status == ObservationStatus.VERIFIED
                    else None,
                    reviewed_at=datetime.now(UTC) if status == ObservationStatus.VERIFIED else None,
                )
            )
            session.flush()
            session.add(
                Observation(
                    organization_id=org_id,
                    asset_id=asset_id,
                    ontology_type=OntologyType.ACTIVITY,
                    subject=activity,
                    predicate="depicted",
                    confidence=0.85,
                    source_kind=SourceKind.AI,
                    source_provider="loadtest",
                    status=status,
                )
            )
            for kind, vector in ((EmbeddingKind.TEXT, tv), (EmbeddingKind.IMAGE, iv)):
                session.add(
                    Embedding(
                        organization_id=org_id,
                        asset_id=asset_id,
                        kind=kind,
                        model=embedder.model_name,
                        vector=vector,
                    )
                )
            if i % 200 == 199:
                session.commit()
        session.commit()
    return embed_seconds, time.perf_counter() - t0


async def run_search_load(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    project_id: str,
    requests: int,
    concurrency: int,
    *,
    use_llm_planner: bool,
) -> tuple[Timings, Timings, int, float, float]:
    """Returns (client timings, server took_ms, errors, wall seconds, mean result count)."""
    timings, server, counts = Timings(), Timings(), []
    errors = 0
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int) -> None:
        nonlocal errors
        async with sem:
            t0 = time.perf_counter()
            r = await client.post(
                "/v1/search",
                headers=headers,
                json={
                    "project_id": project_id,
                    "query": QUERIES[i % len(QUERIES)],
                    "use_llm_planner": use_llm_planner,
                },
            )
            elapsed = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            errors += 1
            return
        body = r.json()
        timings.samples_ms.append(elapsed)
        server.samples_ms.append(float(body["took_ms"]))
        counts.append(len(body["results"]))

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(requests)))
    wall = time.perf_counter() - t0
    return timings, server, errors, wall, statistics.fmean(counts) if counts else 0.0


async def run_benchmark(
    client: httpx.AsyncClient,
    settings: Settings,
    embedder: Embedder | None,
    *,
    assets: int = 1000,
    sites: int = 4,
    requests: int = 300,
    concurrency: int = 10,
    use_llm_planner: bool = False,
    seed: int = 7,
) -> BenchmarkResult:
    if embedder is None:
        raise RuntimeError("Embeddings are disabled (EMBEDDINGS_ENABLED=false); nothing to measure")
    slug = f"loadtest{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer dev.loadtest.{slug}.manager"}
    started = datetime.now(UTC).isoformat(timespec="seconds")
    org_id: uuid.UUID | None = None
    try:
        me = (await client.get("/v1/me", headers=headers)).raise_for_status().json()
        org_id = uuid.UUID(me["organization"]["id"])
        project = (
            (await client.post("/v1/projects", headers=headers, json={"name": "Load test"}))
            .raise_for_status()
            .json()
        )
        site_ids = []
        for i in range(sites):
            site = (
                await client.post(
                    f"/v1/projects/{project['id']}/sites",
                    headers=headers,
                    json={"name": f"Site {chr(65 + i)}", "code": chr(65 + i)},
                )
            ).raise_for_status()
            site_ids.append(uuid.UUID(site.json()["id"]))

        rng = random.Random(seed)
        embed_s, seed_s = await anyio.to_thread.run_sync(
            lambda: seed_corpus(
                org_id, uuid.UUID(project["id"]), site_ids, assets, embedder, rng=rng
            )
        )
        # warm-up (model load, connection pool) is not part of the measurement
        await run_search_load(client, headers, project["id"], 3, 1, use_llm_planner=False)
        timings, server, errors, wall, mean_results = await run_search_load(
            client, headers, project["id"], requests, concurrency, use_llm_planner=use_llm_planner
        )
        return BenchmarkResult(
            assets=assets,
            sites=sites,
            embedder=embedder.model_name,
            seed_seconds=seed_s,
            embed_seconds=embed_s,
            search_requests=requests,
            search_concurrency=concurrency,
            search_errors=errors,
            search_seconds=wall,
            search=timings,
            server_took=server,
            mean_results=mean_results,
            llm_planner=use_llm_planner and settings.search_llm_planner_enabled,
            cloudinary_search=settings.search_cloudinary_enabled,
            started_at=started,
        )
    finally:
        if org_id is not None:
            await anyio.to_thread.run_sync(lambda: cleanup(org_id))


def cleanup(org_id: uuid.UUID) -> None:
    """Delete the throwaway organisation (everything tenant-scoped cascades) and its dev user."""
    with sync_system_session() as session:
        org = session.get(Organization, org_id)
        if org is not None:
            session.delete(org)
        session.execute(delete(User).where(User.external_id.like("dev_user_loadtest%")))
        session.commit()
        assert session.scalar(select(Asset.id).where(Asset.organization_id == org_id)) is None


# --- report -------------------------------------------------------------------------------------------


def per_asset_consumption(settings: Settings) -> list[tuple[str, str]]:
    """What ingesting one photo consumes, from what the pipeline actually calls (no prices)."""
    chain = ", ".join(settings.ai_vision_providers)
    rows = [
        ("Cloudinary upload", "1 authenticated upload (bytes go browser → Cloudinary directly)"),
        (
            "Cloudinary transformations",
            "3 renditions: 2 eager (t_ev_thumb, t_ev_review) + 1 model input (t_ev_ai)",
        ),
        (
            "Cloudinary Analyze (Beta)",
            "3 calls: captioning, image_quality, ai_vision_tagging (skipped if no taxonomy)"
            if settings.cloudinary_analyze_enabled
            else "off (CLOUDINARY_ANALYZE_ENABLED=false)",
        ),
        (
            "Structured extraction",
            f"1 successful call through the provider chain ({chain}); later providers are only "
            "called when earlier ones fail",
        ),
        (
            "OCR / auto-tagging add-ons",
            f"OCR {'1 call when the model reports visible text' if settings.cloudinary_ocr_enabled else 'off'}; "
            f"auto-tagging {'1 call' if settings.cloudinary_auto_tagging else 'off'}",
        ),
        ("Embeddings", f"2 local {settings.embedding_model} passes (image + text); no API cost"),
    ]
    return rows


def format_report(res: BenchmarkResult, settings: Settings) -> str:
    status = "PASS" if res.search_ok else "FAIL"
    lines = [
        "# Evidentia load benchmark (measured locally)",
        "",
        f"Run {res.started_at} · {res.assets:,} assets across {res.sites} sites · embedder "
        f"`{res.embedder}` · LLM planner {'on' if res.llm_planner else 'off'} · Cloudinary Search "
        f"retriever {'on' if res.cloudinary_search else 'off'}.",
        "",
        "Every number below was timed on this machine against the real API app and the real "
        "Postgres database. Produced by `make loadtest`.",
        "",
        "## 1. Search over the corpus",
        "",
        "| Measure | Value |",
        "| :--- | ---: |",
        f"| Requests (concurrency) | {res.search_requests} ({res.search_concurrency}) |",
        f"| Errors | {res.search_errors} |",
        f"| Throughput | {res.qps:.1f} queries/s |",
        f"| Latency p50 / p95 / p99 (end to end) | {res.search.pct(50):.0f} / {res.search.pct(95):.0f} / {res.search.pct(99):.0f} ms |",
        f"| Server-reported search time p50 / p95 | {res.server_took.pct(50):.0f} / {res.server_took.pct(95):.0f} ms |",
        f"| Mean results per query | {res.mean_results:.1f} |",
        f"| PLAN Phase 3 target: p95 < {SEARCH_P95_TARGET_MS:.0f} ms, no errors | **{status}** |",
        "",
        "## 2. Registration (database side of ingestion)",
        "",
        "| Measure | Value |",
        "| :--- | ---: |",
        f"| Embedding {res.assets:,} texts + {res.assets:,} image vectors | {res.embed_seconds:.1f} s |",
        f"| Writing assets + observations + embeddings | {res.seed_seconds:.1f} s ({res.seed_rate:.0f} assets/s) |",
        "",
        "## 3. Not measured here",
        "",
        "Cloudinary upload and transformations, Cloudinary Analyze, LLM/VLM calls and network time are "
        "excluded: they spend account quota and depend on the plan and region. End-to-end ingestion time "
        "per job is in the worker logs; latency of real AI calls is on the project analytics page.",
        "",
        "## 4. What one photo consumes",
        "",
        "| Service | Per asset |",
        "| :--- | :--- |",
        *[f"| {k} | {v} |" for k, v in per_asset_consumption(settings)],
        "",
        "To turn this into money, use your Cloudinary plan's credit rules (Console → Usage) and your "
        "Gemini/Groq tier; prices are deliberately not guessed here.",
        "",
    ]
    return "\n".join(lines)


def result_summary(res: BenchmarkResult) -> dict[str, Any]:
    return {
        "assets": res.assets,
        "search_p50_ms": round(res.search.pct(50), 1),
        "search_p95_ms": round(res.search.pct(95), 1),
        "qps": round(res.qps, 1),
        "errors": res.search_errors,
        "seed_assets_per_s": round(res.seed_rate, 1),
        "pass": res.search_ok,
    }
