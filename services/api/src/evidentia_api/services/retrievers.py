"""Independent retrievers for hybrid search. Each applies the plan's hard filters and returns a
ranked list of Hits; fusion happens in services/search.py.

  structured   filters only, newest first (used when there is no free text)
  activity     assets with a matching activity observation (verified > AI confidence)
  lexical      Postgres full-text over the search document (captions, observations, OCR, notes)
  text_vector  SigLIP text embedding of the query vs. the search document's embedding
  visual       SigLIP text -> image embeddings (what should be *visible*), calibrated probability
  segments     SigLIP text embedding of the query vs. one vector per video time span
  cloudinary   Cloudinary Search API over the tags/context we mirror into Cloudinary
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

import anyio
import cloudinary.search
import structlog
from evidentia_core.db.models import Asset, Embedding, Observation
from evidentia_core.domain.enums import AssetState, EmbeddingKind, ObservationStatus, OntologyType
from evidentia_core.domain.ranking import Hit
from evidentia_core.domain.search_plan import SearchFilters
from evidentia_ml.embeddings import Embedder
from sqlalchemy import ColumnElement, and_, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger("evidentia.search")

SEARCHABLE = (AssetState.READY, AssetState.REVIEW_REQUIRED)
_WORD = re.compile(r"[A-Za-z0-9]{2,}")
_STOP = frozenset(
    [
        "the",
        "and",
        "with",
        "from",
        "for",
        "that",
        "this",
        "are",
        "was",
        "were",
        "has",
        "have",
        "into",
        "onto",
        "over",
        "near",
        "show",
        "shows",
        "showing",
        "photo",
        "photos",
        "image",
        "images",
        "picture",
        "pictures",
        "video",
        "videos",
    ]
)


def filter_conditions(project_id: uuid.UUID, f: SearchFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [Asset.project_id == project_id, Asset.state.in_(SEARCHABLE)]
    if f.site_ids:
        conds.append(Asset.site_id.in_([uuid.UUID(s) for s in f.site_ids]))
    if f.date_from:
        conds.append(Asset.capture_time >= datetime.combine(f.date_from, time.min, UTC))
    if f.date_to:
        conds.append(
            Asset.capture_time < datetime.combine(f.date_to + timedelta(days=1), time.min, UTC)
        )
    if f.media_type:
        conds.append(Asset.resource_type == f.media_type)
    if f.needs_review:
        conds.append(Asset.state == AssetState.REVIEW_REQUIRED)
    if f.people_present:
        conds.append(Asset.flags["people_present"].as_boolean().is_(True))
    if f.verified_only:
        if f.activities:
            conds.append(
                Asset.verified_activities.op("?|")(literal(f.activities, type_=_text_array()))
            )
        else:
            conds.append(Asset.reviewed_at.is_not(None))
    return conds


def _text_array() -> Any:
    from sqlalchemy.dialects.postgresql import ARRAY
    from sqlalchemy.types import Text

    return ARRAY(Text)


async def structured(db: AsyncSession, conds: list[ColumnElement[bool]], limit: int) -> list[Hit]:
    rows = await db.execute(
        select(Asset.id)
        .where(*conds)
        .order_by(Asset.capture_time.desc().nulls_last(), Asset.created_at.desc())
        .limit(limit)
    )
    return [Hit(str(r.id), i + 1) for i, r in enumerate(rows)]


async def activity(
    db: AsyncSession, conds: list[ColumnElement[bool]], activities: list[str], limit: int
) -> list[Hit]:
    if not activities:
        return []
    verified = func.bool_or(Observation.status == ObservationStatus.VERIFIED)
    best = func.max(func.coalesce(Observation.confidence, 0.6))
    rows = await db.execute(
        select(
            Asset.id,
            verified.label("verified"),
            best.label("confidence"),
            func.array_agg(func.distinct(Observation.subject)).label("subjects"),
        )
        .join(Observation, Observation.asset_id == Asset.id)
        .where(
            *conds,
            Observation.ontology_type == OntologyType.ACTIVITY,
            Observation.subject.in_(activities),
            Observation.status.in_([ObservationStatus.PROPOSED, ObservationStatus.VERIFIED]),
        )
        .group_by(Asset.id)
        .order_by(verified.desc(), best.desc())
        .limit(limit)
    )
    return [
        Hit(
            str(r.id),
            i + 1,
            float(r.confidence),
            {"verified": bool(r.verified), "activities": list(r.subjects)},
        )
        for i, r in enumerate(rows)
    ]


def _or_tsquery(query: str) -> str | None:
    words = [w.lower() for w in _WORD.findall(query)][:20]
    return " | ".join(dict.fromkeys(words)) or None


async def lexical(
    db: AsyncSession, conds: list[ColumnElement[bool]], query: str, limit: int
) -> list[Hit]:
    """Full-text search. Documents containing ALL query words first; only when none does, any
    word (those hits are marked `some_terms` and later down-ranked for the words they lack)."""
    q_any = _or_tsquery(query)
    if not q_any:
        return []
    for tsq, match in (
        (func.plainto_tsquery("english", query), "all_terms"),
        (func.to_tsquery("english", q_any), "some_terms"),
    ):
        rank = func.ts_rank_cd(Asset.search_tsv, tsq)
        rows = (
            await db.execute(
                select(Asset.id, rank.label("rank"))
                .where(*conds, Asset.search_tsv.op("@@")(tsq))
                .order_by(rank.desc())
                .limit(limit)
            )
        ).all()
        if rows:
            return [
                Hit(str(r.id), i + 1, float(r.rank), {"match": match}) for i, r in enumerate(rows)
            ]
    return []


async def term_coverage(
    db: AsyncSession, query: str, asset_ids: list[uuid.UUID]
) -> tuple[list[str], dict[str, list[str]]]:
    """The query's content words (stop words dropped) and, per asset, the ones its search
    document does not contain (compared as English stems: 'eating' matches 'eat')."""
    words = list(dict.fromkeys(w.lower() for w in _WORD.findall(query)))[:20]
    if not words or not asset_ids:
        return [], {}
    rows = await db.execute(
        text(
            "SELECT w, tsvector_to_array(to_tsvector('english', w)) "
            "FROM unnest(CAST(:words AS text[])) AS w"
        ),
        {"words": words},
    )
    stems = {w: set(arr) for w, arr in rows.all() if arr}
    terms = [w for w in words if w in stems]
    if not terms:
        return [], {}
    docs = await db.execute(
        select(Asset.id, func.tsvector_to_array(Asset.search_tsv)).where(Asset.id.in_(asset_ids))
    )
    missing = {}
    for asset_id, lexemes in docs.all():
        have = set(lexemes or [])
        missing[str(asset_id)] = [w for w in terms if not stems[w] <= have]
    return terms, missing


async def vector_search(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    kind: EmbeddingKind,
    model: str,
    vector: list[float],
    limit: int,
) -> list[tuple[str, float]]:
    # pgvector >= 0.8: keep scanning the HNSW index until enough rows pass the filters.
    await db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    await db.execute(text("SET LOCAL hnsw.ef_search = 200"))
    distance = Embedding.vector.cosine_distance(vector)
    rows = await db.execute(
        select(Asset.id, distance.label("distance"))
        .join(
            Embedding,
            and_(Embedding.asset_id == Asset.id, Embedding.kind == kind, Embedding.model == model),
        )
        .where(*conds)
        .order_by(distance)
        .limit(limit)
    )
    return [(str(r.id), 1.0 - float(r.distance)) for r in rows]


async def text_vector(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    embedder: Embedder,
    query_vector: list[float],
    limit: int,
    margin: float,
    min_similarity: float = 0.0,
) -> list[Hit]:
    pairs = await vector_search(
        db, conds, EmbeddingKind.TEXT, embedder.model_name, query_vector, limit
    )
    if not pairs:
        return []
    best = pairs[0][1]
    # relative cut drops the long tail; the absolute floor drops "best of a bad lot"
    floor = max(best - margin, min_similarity)
    kept = [(aid, sim) for aid, sim in pairs if sim >= floor]
    return [Hit(aid, i + 1, sim) for i, (aid, sim) in enumerate(kept)]


async def segments(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    embedder: Embedder,
    query_vector: list[float],
    limit: int,
    margin: float,
    min_similarity: float = 0.0,
) -> list[Hit]:
    """Best matching video span per asset. The hit's detail carries start_ms/end_ms."""
    await db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    await db.execute(text("SET LOCAL hnsw.ef_search = 200"))
    distance = Embedding.vector.cosine_distance(query_vector)
    ranked = (
        select(
            Asset.id.label("id"),
            Embedding.start_ms.label("start_ms"),
            Embedding.end_ms.label("end_ms"),
            distance.label("distance"),
        )
        .join(
            Embedding,
            and_(
                Embedding.asset_id == Asset.id,
                Embedding.kind == EmbeddingKind.SEGMENT,
                Embedding.model == embedder.model_name,
            ),
        )
        .where(*conds, Embedding.start_ms.is_not(None), Embedding.end_ms.is_not(None))
        .order_by(Asset.id, distance)
        .distinct(Asset.id)
    ).subquery()
    rows = (await db.execute(select(ranked).order_by(ranked.c.distance).limit(limit))).all()
    if not rows:
        return []
    scored = [(r.id, 1.0 - float(r.distance), int(r.start_ms), int(r.end_ms)) for r in rows]
    best = scored[0][1]
    kept = [row for row in scored if row[1] >= max(best - margin, min_similarity)]
    return [
        Hit(
            str(aid),
            i + 1,
            sim,
            {"start_ms": start_ms, "end_ms": end_ms},
        )
        for i, (aid, sim, start_ms, end_ms) in enumerate(kept)
    ]


async def visual(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    embedder: Embedder,
    query_vector: list[float],
    limit: int,
    min_probability: float,
) -> list[Hit]:
    pairs = await vector_search(
        db, conds, EmbeddingKind.IMAGE, embedder.model_name, query_vector, limit
    )
    hits = []
    for aid, sim in pairs:
        probability = embedder.match_probability(sim)
        if probability >= min_probability:
            hits.append(Hit(aid, len(hits) + 1, sim, {"probability": round(probability, 4)}))
    return hits


def cloudinary_expression(project_id: uuid.UUID, activities: list[str], query: str) -> str:
    parts = [f"tags=proj_{project_id}"]
    if activities:
        tags = " OR ".join(
            f"tags=ai_{a} OR tags=declared_{a} OR tags=verified_{a}" for a in activities
        )
        parts.append(f"({tags})")
    # every content word must match (OR let "man" alone match "a man eating apple")
    words = [w for w in _WORD.findall(query) if len(w) >= 3 and w.lower() not in _STOP][:8]
    if words:
        parts.append("(" + " AND ".join(words) + ")")
    return " AND ".join(parts)


async def cloudinary_search(
    project_id: uuid.UUID,
    activities: list[str],
    query: str,
    limit: int,
    deadline_seconds: float = 3.0,
) -> list[Hit]:
    """Runs the Cloudinary Search API (counts toward Admin API rate limits: best-effort only)."""
    if not activities and not _WORD.search(query):
        return []
    expression = cloudinary_expression(project_id, activities, query)

    def run() -> dict[str, Any]:
        return dict(
            cloudinary.search.Search().expression(expression).max_results(min(limit, 100)).execute()
        )

    with anyio.fail_after(deadline_seconds):
        response = await anyio.to_thread.run_sync(run)
    hits = []
    for i, resource in enumerate(response.get("resources") or []):
        public_id = str(resource.get("public_id", ""))
        try:
            uuid.UUID(public_id)
        except ValueError:
            continue
        hits.append(Hit(public_id, i + 1, None, {"expression": expression}))
    return hits


async def matched_observations(
    db: AsyncSession, asset_ids: list[uuid.UUID], activities: list[str]
) -> dict[uuid.UUID, list[Observation]]:
    if not asset_ids:
        return {}
    query = select(Observation).where(
        Observation.asset_id.in_(asset_ids),
        Observation.status.in_([ObservationStatus.PROPOSED, ObservationStatus.VERIFIED]),
        Observation.ontology_type.in_(
            [OntologyType.ACTIVITY, OntologyType.CONDITION, OntologyType.OBJECT]
        ),
    )
    out: dict[uuid.UUID, list[Observation]] = {}
    for obs in (await db.scalars(query)).all():
        out.setdefault(obs.asset_id, []).append(obs)
    for aid, items in out.items():
        items.sort(
            key=lambda o: (
                o.subject not in activities,
                o.status != ObservationStatus.VERIFIED,
                -(o.confidence or 0),
            )
        )
        out[aid] = items[:4]
    return out
