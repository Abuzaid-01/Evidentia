"""Search indexing: the asset's search document (Postgres full-text) + SigLIP embeddings.

Runs as the last part of enrichment (before INDEXED) and again whenever a review changes what an
asset is believed to show. Embeddings are skipped when their source is unchanged (source_hash).
Embedding failures never fail the asset: it stays searchable lexically and is flagged.
"""

from __future__ import annotations

import hashlib

import structlog
from evidentia_core.db.models import Asset, Embedding, Observation, Project, Site, Taxonomy
from evidentia_core.domain.enums import EmbeddingKind, ObservationStatus, OntologyType
from evidentia_core.domain.search_doc import ObservationText, build_search_text, content_hash
from evidentia_core.domain.video import segment_text, span_bounds
from evidentia_ml.embeddings import Embedder
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from evidentia_worker.context import WorkerContext

log = structlog.get_logger("evidentia.indexing")

_LIVE = (ObservationStatus.PROPOSED, ObservationStatus.VERIFIED)


def refresh_search_text(session: Session, asset: Asset) -> str:
    observations = list(
        session.scalars(
            select(Observation).where(
                Observation.asset_id == asset.id, Observation.status.in_(_LIVE)
            )
        )
    )
    project = session.get(Project, asset.project_id)
    taxonomy = session.scalar(
        select(Taxonomy).where(
            Taxonomy.project_id == asset.project_id,
            Taxonomy.version == (project.active_taxonomy_version if project else 1),
        )
    )
    labels = {a["key"]: a["label"] for a in (taxonomy.activities if taxonomy else [])}
    site = session.get(Site, asset.site_id) if asset.site_id else None
    asset.search_text = build_search_text(
        caption=asset.caption,
        observations=[
            ObservationText(
                o.ontology_type.value, o.subject, o.predicate, o.status.value, o.value, o.confidence
            )
            for o in observations
        ],
        activity_labels=labels,
        site_name=site.name if site else None,
        filename=asset.original_filename,
        note=asset.contributor_note,
    )
    asset.verified_activities = (
        sorted(
            {
                o.subject
                for o in observations
                if o.ontology_type == OntologyType.ACTIVITY
                and o.status == ObservationStatus.VERIFIED
                and o.subject != "other"
            }
        )
        or None
    )
    return asset.search_text


def _upsert(
    session: Session,
    asset: Asset,
    kind: EmbeddingKind,
    model: str,
    vector: list[float],
    source: str,
    *,
    segment_key: str = "",
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> None:
    stmt = insert(Embedding).values(
        organization_id=asset.organization_id,
        asset_id=asset.id,
        kind=kind,
        model=model,
        vector=vector,
        source_hash=source,
        segment_key=segment_key,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                Embedding.asset_id,
                Embedding.kind,
                Embedding.model,
                Embedding.segment_key,
            ],
            set_={
                "vector": stmt.excluded.vector,
                "source_hash": stmt.excluded.source_hash,
                "start_ms": stmt.excluded.start_ms,
                "end_ms": stmt.excluded.end_ms,
            },
        )
    )


def _current_hash(session: Session, asset: Asset, kind: EmbeddingKind, model: str) -> str | None:
    return session.scalar(
        select(Embedding.source_hash).where(
            Embedding.asset_id == asset.id, Embedding.kind == kind, Embedding.model == model
        )
    )


def index_asset(
    session: Session, asset: Asset, ctx: WorkerContext, *, image: bytes | None = None
) -> None:
    text = refresh_search_text(session, asset)
    flags = dict(asset.flags or {})
    embedder = ctx.embedder
    if embedder is None:
        flags["embeddings"] = "disabled"
        asset.flags = flags
        return
    try:
        text_hash = content_hash(text)
        if (
            text
            and _current_hash(session, asset, EmbeddingKind.TEXT, embedder.model_name) != text_hash
        ):
            _upsert(
                session,
                asset,
                EmbeddingKind.TEXT,
                embedder.model_name,
                embedder.embed_texts([text])[0],
                text_hash,
            )
        if image is not None:
            image_hash = hashlib.sha256(image).hexdigest()
            if (
                _current_hash(session, asset, EmbeddingKind.IMAGE, embedder.model_name)
                != image_hash
            ):
                _upsert(
                    session,
                    asset,
                    EmbeddingKind.IMAGE,
                    embedder.model_name,
                    embedder.embed_images([image])[0],
                    image_hash,
                )
        _sync_segments(session, asset, embedder)
        flags["embeddings"] = embedder.model_name
        flags.pop("embeddings_error", None)
    except Exception as exc:  # model/runtime issues must not block the evidence pipeline
        log.exception("embedding_failed", asset_id=str(asset.id))
        flags["embeddings_error"] = str(exc)[:300]
    asset.flags = flags


def _sync_segments(session: Session, asset: Asset, embedder: Embedder) -> None:
    """One vector per video time span, so a search hit can name that span."""
    observations = list(
        session.scalars(
            select(Observation).where(
                Observation.asset_id == asset.id, Observation.status.in_(_LIVE)
            )
        )
    )
    project = session.get(Project, asset.project_id)
    taxonomy = session.scalar(
        select(Taxonomy).where(
            Taxonomy.project_id == asset.project_id,
            Taxonomy.version == (project.active_taxonomy_version if project else 1),
        )
    )
    labels = {a["key"]: a["label"] for a in (taxonomy.activities if taxonomy else [])}
    grouped: dict[tuple[int, int], list[str]] = {}
    for obs in observations:
        bounds = span_bounds(obs.evidence_span)
        if bounds is None:
            continue
        text = segment_text(obs.ontology_type.value, obs.subject, obs.value, labels)
        if text:
            grouped.setdefault(bounds, []).append(text)
    wanted: dict[str, tuple[int, int, str]] = {}
    for (start_ms, end_ms), parts in grouped.items():
        key = f"{start_ms}:{end_ms}"
        blob = "\n".join(dict.fromkeys(parts))[:2000]
        wanted[key] = (start_ms, end_ms, blob)

    stale = delete(Embedding).where(
        Embedding.asset_id == asset.id, Embedding.kind == EmbeddingKind.SEGMENT
    )
    if wanted:
        stale = stale.where(Embedding.segment_key.not_in(list(wanted)))
    session.execute(stale)
    if not wanted:
        return

    existing = {
        key: source
        for key, source in session.execute(
            select(Embedding.segment_key, Embedding.source_hash).where(
                Embedding.asset_id == asset.id,
                Embedding.kind == EmbeddingKind.SEGMENT,
                Embedding.model == embedder.model_name,
            )
        )
    }
    pending = [
        (key, start, end, text)
        for key, (start, end, text) in wanted.items()
        if existing.get(key) != content_hash(text)
    ]
    if not pending:
        return
    vectors = embedder.embed_texts([text for _, _, _, text in pending])
    for (key, start_ms, end_ms, text), vector in zip(pending, vectors, strict=True):
        _upsert(
            session,
            asset,
            EmbeddingKind.SEGMENT,
            embedder.model_name,
            vector,
            content_hash(text),
            segment_key=key,
            start_ms=start_ms,
            end_ms=end_ms,
        )
