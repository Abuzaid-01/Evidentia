"""Hybrid evidence search: plan -> retrievers (in sequence on one session) -> RRF -> quality -> explain."""

from __future__ import annotations

import time
import uuid
from datetime import date
from typing import Any

import anyio
import structlog
from evidentia_ai.planner import plan_query
from evidentia_ai.text_llm import TextLLM
from evidentia_core.config import Settings
from evidentia_core.db.models import Asset, Embedding, SearchFeedback, SearchQuery, Site, Taxonomy
from evidentia_core.domain.enums import AssetState, EmbeddingKind
from evidentia_core.domain.ranking import (
    Fused,
    Hit,
    QualitySignals,
    apply_adjustments,
    coverage_multiplier,
    explain,
    quality_multiplier,
    reciprocal_rank_fusion,
)
from evidentia_core.domain.search_plan import ActivityRef, SearchFilters, SearchPlan, SiteRef
from evidentia_core.domain.video import span_label
from evidentia_ml.embeddings import Embedder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.errors import NotFound, Unprocessable
from evidentia_api.schemas.search import (
    MatchedObservation,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SimilarResult,
    VideoSpan,
)
from evidentia_api.services import retrievers as r
from evidentia_api.services.assets import to_summary
from evidentia_api.services.projects import get_project

log = structlog.get_logger("evidentia.search")


async def _plan_context(
    db: AsyncSession, project_id: uuid.UUID
) -> tuple[list[SiteRef], list[ActivityRef]]:
    project = await get_project(db, project_id)
    sites = (await db.scalars(select(Site).where(Site.project_id == project.id))).all()
    taxonomy = await db.scalar(
        select(Taxonomy).where(
            Taxonomy.project_id == project.id, Taxonomy.version == project.active_taxonomy_version
        )
    )
    return (
        [SiteRef(str(s.id), s.code, s.name) for s in sites],
        [ActivityRef(a["key"], a["label"]) for a in (taxonomy.activities if taxonomy else [])],
    )


def _merge_filters(parsed: SearchFilters, explicit: SearchFilters | None) -> SearchFilters:
    if explicit is None:
        return parsed
    merged = parsed.model_copy()
    for field, value in explicit.model_dump(exclude_defaults=True).items():
        setattr(merged, field, value)
    return merged


async def build_plan(
    db: AsyncSession, body: SearchRequest, settings: Settings, llms: list[TextLLM]
) -> tuple[SearchPlan, list[SiteRef], list[ActivityRef]]:
    sites, activities = await _plan_context(db, body.project_id)
    use_llm = (
        body.use_llm_planner and settings.search_llm_planner_enabled and bool(body.query.strip())
    )
    plan = await anyio.to_thread.run_sync(
        lambda: plan_query(
            body.query,
            sites=sites,
            activities=activities,
            today=date.today(),
            llms=llms if use_llm else None,
        )
    )
    plan.filters = _merge_filters(plan.filters, body.filters)
    return plan, sites, activities


async def _embed(embedder: Embedder | None, text: str) -> list[float] | None:
    if embedder is None or not text.strip():
        return None
    vectors = await anyio.to_thread.run_sync(embedder.embed_texts, [text])
    return vectors[0]


async def run_search(
    db: AsyncSession,
    principal: Principal,
    body: SearchRequest,
    settings: Settings,
    *,
    embedder: Embedder | None,
    llms: list[TextLLM],
    cloudinary_ready: bool,
) -> SearchResponse:
    started = time.perf_counter()
    plan, _sites, _activities = await build_plan(db, body, settings, llms)
    f = plan.filters
    conds = r.filter_conditions(body.project_id, f)
    n = settings.search_candidates_per_retriever
    has_text = bool(plan.semantic_text.strip() or plan.visual_text.strip())

    results: dict[str, list[Hit]] = {}
    stats: dict[str, dict[str, Any]] = {}

    async def run(name: str, coro: Any) -> None:
        t0 = time.perf_counter()
        try:
            hits = await coro
            results[name] = hits
            stats[name] = {"hits": len(hits), "ms": round((time.perf_counter() - t0) * 1000)}
        except Exception as exc:  # one retriever failing never fails the search
            log.warning("retriever_failed", retriever=name, error=str(exc))
            stats[name] = {"error": type(exc).__name__}

    if not has_text and not f.activities:
        await run("structured", r.structured(db, conds, n))
    await run("activity", r.activity(db, conds, f.activities, n))
    if plan.semantic_text:
        await run("lexical", r.lexical(db, conds, plan.semantic_text, n))
    if embedder is not None and has_text:
        text_vec = await _embed(embedder, plan.semantic_text or plan.visual_text)
        visual_vec = (
            text_vec
            if plan.visual_text == plan.semantic_text
            else await _embed(embedder, plan.visual_text)
        )
        if text_vec is not None:
            await run(
                "text_vector",
                r.text_vector(
                    db,
                    conds,
                    embedder,
                    text_vec,
                    n,
                    settings.search_text_vector_margin,
                    settings.search_text_vector_min_similarity,
                ),
            )
        segment_vec = text_vec or visual_vec
        if segment_vec is not None:
            await run(
                "segments",
                r.segments(
                    db,
                    conds,
                    embedder,
                    segment_vec,
                    n,
                    settings.search_text_vector_margin,
                    settings.search_text_vector_min_similarity,
                ),
            )
        if visual_vec is not None:
            await run(
                "visual",
                r.visual(
                    db, conds, embedder, visual_vec, n, settings.search_visual_min_probability
                ),
            )
    if cloudinary_ready and settings.search_cloudinary_enabled and has_text:
        await run(
            "cloudinary", r.cloudinary_search(body.project_id, f.activities, plan.semantic_text, n)
        )

    fused = reciprocal_rank_fusion({k: v for k, v in results.items() if v}, k=settings.search_rrf_k)

    # Load candidates through the SAME hard filters (Cloudinary hits are post-filtered here).
    candidate_ids = [
        uuid.UUID(a) for a in sorted(fused, key=lambda a: -fused[a].score)[: body.limit * 4]
    ]
    assets = {
        a.id: a
        for a in (await db.scalars(select(Asset).where(Asset.id.in_(candidate_ids), *conds))).all()
    }
    terms, missing = (
        await r.term_coverage(db, plan.semantic_text, list(assets))
        if plan.semantic_text
        else ([], {})
    )
    for aid, entry in fused.items():
        # a match by meaning (above the calibrated floor) covers the query even when the words
        # differ ("worker" vs "man"); literal word checks would wrongly flag it as partial
        if {"text_vector", "segments"} & entry.contributions.keys():
            missing[aid] = []
    for aid in list(fused):
        asset = assets.get(uuid.UUID(aid))
        if asset is None:
            del fused[aid]
            continue
        verified_match = bool(set(asset.verified_activities or []) & set(f.activities))
        adjustments = quality_multiplier(
            QualitySignals(
                verified_activity_match=verified_match,
                review_required=asset.state == AssetState.REVIEW_REQUIRED,
                exact_duplicate=asset.exact_duplicate_of_id is not None,
                quality_score=asset.quality_score,
            )
        )
        adjustments |= coverage_multiplier(len(missing.get(aid, [])), len(terms))
        apply_adjustments(fused[aid], adjustments)
    ranked = sorted(fused.values(), key=lambda e: -e.score)[: body.limit]
    ids = [uuid.UUID(e.asset_id) for e in ranked]
    matched = await r.matched_observations(db, ids, f.activities)

    out = [
        SearchResult(
            asset=to_summary(
                assets[uuid.UUID(e.asset_id)], settings, cloudinary_ready=cloudinary_ready
            ),
            score=round(e.score, 6),
            reasons=explain(e)
            + (
                [f"doesn't mention: {', '.join(missing[e.asset_id])}"]
                if missing.get(e.asset_id)
                else []
            ),
            missing_terms=missing.get(e.asset_id, []),
            contributions=e.contributions,
            video_span=_video_span(e),
            matched_observations=[
                MatchedObservation(
                    id=o.id,
                    ontology_type=o.ontology_type.value,
                    subject=o.subject,
                    predicate=o.predicate,
                    confidence=o.confidence,
                    status=o.status.value,
                )
                for o in matched.get(uuid.UUID(e.asset_id), [])
            ],
        )
        for e in ranked
    ]
    took_ms = round((time.perf_counter() - started) * 1000)
    log_entry = SearchQuery(
        organization_id=principal.org_id,
        user_id=principal.user_id,
        project_id=body.project_id,
        query=body.query,
        plan=plan.model_dump(mode="json"),
        result_ids=[str(i) for i in ids],
        retrievers=stats,
        took_ms=took_ms,
    )
    db.add(log_entry)
    await db.commit()
    return SearchResponse(
        query_id=log_entry.id,
        plan=plan,
        results=out,
        retrievers=stats,
        took_ms=took_ms,
        query_terms=terms,
        complete_matches=sum(1 for e in ranked if not missing.get(e.asset_id)),
    )


def _video_span(entry: Fused) -> VideoSpan | None:
    segment = entry.contributions.get("segments") or {}
    start, end = segment.get("start_ms"), segment.get("end_ms")
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    return VideoSpan(start_ms=start, end_ms=end, label=span_label(start, end))


async def similar(
    db: AsyncSession,
    asset_id: uuid.UUID,
    limit: int,
    same_project: bool,
    settings: Settings,
    *,
    embedder: Embedder | None,
    cloudinary_ready: bool,
) -> list[SimilarResult]:
    """Image -> image: 'find more photos like this one' (same scene over time, duplicates, angles)."""
    if embedder is None:
        raise Unprocessable("Embeddings are disabled (EMBEDDINGS_ENABLED=false)")
    source = await db.get(Asset, asset_id)
    if source is None:
        raise NotFound("Asset not found")
    vector = await db.scalar(
        select(Embedding.vector).where(
            Embedding.asset_id == asset_id,
            Embedding.kind == EmbeddingKind.IMAGE,
            Embedding.model == embedder.model_name,
        )
    )
    if vector is None:
        raise Unprocessable(
            "This asset has no image embedding yet (still processing or indexing failed)"
        )
    conds = [Asset.state.in_(r.SEARCHABLE), Asset.id != asset_id]
    if same_project:
        conds.append(Asset.project_id == source.project_id)
    pairs = await r.vector_search(
        db, conds, EmbeddingKind.IMAGE, embedder.model_name, list(vector), limit
    )
    assets = {
        a.id: a
        for a in (
            await db.scalars(select(Asset).where(Asset.id.in_([uuid.UUID(p[0]) for p in pairs])))
        ).all()
    }
    return [
        SimilarResult(
            asset=to_summary(assets[uuid.UUID(aid)], settings, cloudinary_ready=cloudinary_ready),
            similarity=round(sim, 4),
        )
        for aid, sim in pairs
        if uuid.UUID(aid) in assets
    ]


async def record_feedback(
    db: AsyncSession,
    principal: Principal,
    query_id: uuid.UUID,
    asset_id: uuid.UUID,
    action: Any,
    rank: int | None,
) -> None:
    query = await db.get(SearchQuery, query_id)
    if query is None:
        raise NotFound("Search query not found")
    db.add(
        SearchFeedback(
            organization_id=principal.org_id,
            query_id=query_id,
            asset_id=asset_id,
            user_id=principal.user_id,
            action=action,
            rank=rank,
        )
    )
    await db.commit()
