"""Before/after pairs: candidate generation, human decisions and presentation.

Candidates come from one SQL query that does what the plan asks, in the database:
  * same site (or, for photos without a site, GPS positions within the distance limit),
  * PostGIS `ST_DWithin` / `ST_Distance` between capture positions,
  * the baseline and endline windows, with a minimum gap and no identical files,
  * pgvector cosine similarity between the photos' SigLIP image embeddings,
  * the best `per_anchor` baseline photos for each endline photo (window function).
Geometric verification and change detection then run in the worker (tasks/before_after.py);
the final ranking combines both, and a human confirms before a pair can back a claim.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import structlog
from evidentia_cloudinary.composite import signed_url
from evidentia_cloudinary.delivery import rendition_url
from evidentia_core import tasks
from evidentia_core.config import Settings
from evidentia_core.db.models import Asset, BeforeAfterPair, Claim, EvidenceLink
from evidentia_core.domain import before_after as rules
from evidentia_core.domain.enums import AssetState, PairOrigin, PairStatus, ResourceType
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.errors import Conflict, NotFound, Unprocessable
from evidentia_api.schemas.before_after import (
    PairClaimRef,
    PairCreate,
    PairDecision,
    PairDetail,
    PairPhoto,
    PairSummary,
    SuggestOut,
    SuggestRequest,
    Windows,
)
from evidentia_api.services import audit
from evidentia_api.services.assets import thumb_url
from evidentia_api.services.projects import get_project, get_site

log = structlog.get_logger("evidentia.before_after")

PAIRABLE_STATES = (AssetState.READY, AssetState.REVIEW_REQUIRED)
REANALYSABLE = {PairStatus.CANDIDATE, PairStatus.ANALYZED, PairStatus.FAILED}


# --- loading ---------------------------------------------------------------------------------------


async def get_pair(db: AsyncSession, pair_id: uuid.UUID, *, lock: bool = False) -> BeforeAfterPair:
    query = select(BeforeAfterPair).where(BeforeAfterPair.id == pair_id)
    pair = await db.scalar(query.with_for_update() if lock else query)
    if pair is None:
        raise NotFound("Before/after pair not found")
    return pair


async def _assets(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, Asset]:
    if not ids:
        return {}
    return {a.id: a for a in (await db.scalars(select(Asset).where(Asset.id.in_(ids)))).all()}


# --- candidate generation ------------------------------------------------------------------------------

_CANDIDATES_SQL = """
WITH after_photos AS (
    SELECT id, site_id, capture_time, location, sha256 FROM assets
    WHERE {after_where}
), before_photos AS (
    SELECT id, site_id, capture_time, location, sha256 FROM assets
    WHERE {before_where}
), scored AS (
    SELECT
        a.id AS after_id,
        b.id AS before_id,
        coalesce(a.site_id, b.site_id) AS site_id,
        ST_Distance(a.location, b.location) AS distance_m,
        1 - (ea.vector <=> eb.vector) AS similarity,
        (a.capture_time::date - b.capture_time::date) AS days_apart
    FROM after_photos a
    JOIN before_photos b
      ON b.id <> a.id
     AND a.site_id IS NOT DISTINCT FROM b.site_id
     AND (a.site_id IS NOT NULL OR (a.location IS NOT NULL AND b.location IS NOT NULL))
     AND a.capture_time - b.capture_time >= make_interval(days => :min_gap)
     AND (a.sha256 IS NULL OR b.sha256 IS NULL OR a.sha256 <> b.sha256)
     AND (a.location IS NULL OR b.location IS NULL OR ST_DWithin(a.location, b.location, :max_m))
    LEFT JOIN embeddings ea
      ON ea.asset_id = a.id AND ea.kind = 'image' AND ea.model = :model AND ea.segment_key = ''
    LEFT JOIN embeddings eb
      ON eb.asset_id = b.id AND eb.kind = 'image' AND eb.model = :model AND eb.segment_key = ''
), ranked AS (
    SELECT *, row_number() OVER (
        PARTITION BY after_id
        ORDER BY similarity DESC NULLS LAST, distance_m ASC NULLS LAST, days_apart DESC, before_id
    ) AS rn
    FROM scored
)
SELECT after_id, before_id, site_id, distance_m, similarity, days_apart
FROM ranked WHERE rn <= :per_anchor
ORDER BY after_id, rn
LIMIT :limit
"""


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, UTC)


def _photo_where(
    prefix: str, start: date | None, end: date | None, params: dict[str, Any]
) -> list[str]:
    where = [
        "project_id = :project_id",
        "resource_type = 'image'",
        "state IN ('ready', 'review_required')",
        "capture_time IS NOT NULL",
    ]
    if start:
        params[f"{prefix}_from"] = _day_start(start)
        where.append(f"capture_time >= :{prefix}_from")
    if end:
        params[f"{prefix}_to"] = _day_start(end + timedelta(days=1))
        where.append(f"capture_time < :{prefix}_to")
    return where


async def _windows(
    db: AsyncSession, project_id: uuid.UUID, body: SuggestRequest, anchor: Asset | None
) -> rules.Windows | None:
    explicit = rules.Windows(
        body.baseline_from, body.baseline_to, body.endline_from, body.endline_to
    )
    if anchor is not None:
        assert anchor.capture_time is not None
        latest_before = (anchor.capture_time - timedelta(days=body.min_gap_days)).date()
        return rules.Windows(
            body.baseline_from,
            min(body.baseline_to or latest_before, latest_before),
            anchor.capture_time.date(),
            anchor.capture_time.date(),
        )
    if any(
        (explicit.baseline_from, explicit.baseline_to, explicit.endline_from, explicit.endline_to)
    ):
        return explicit
    query = select(func.date(Asset.capture_time)).where(
        Asset.project_id == project_id,
        Asset.resource_type == ResourceType.IMAGE,
        Asset.state.in_(PAIRABLE_STATES),
        Asset.capture_time.is_not(None),
    )
    if body.site_id:
        query = query.where(Asset.site_id == body.site_id)
    return rules.default_windows(list((await db.scalars(query)).all()))


async def suggest(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    body: SuggestRequest,
    settings: Settings,
    *,
    cloudinary_ready: bool,
    rid: str | None,
) -> SuggestOut:
    await get_project(db, project_id)
    if body.site_id and (await get_site(db, body.site_id)).project_id != project_id:
        raise Unprocessable("Site does not belong to this project")
    anchor = None
    if body.anchor_asset_id:
        anchor = await db.get(Asset, body.anchor_asset_id)
        if anchor is None or anchor.project_id != project_id:
            raise Unprocessable("Anchor photo not found in this project")
        if anchor.resource_type != ResourceType.IMAGE or anchor.capture_time is None:
            raise Unprocessable("The anchor must be a photo with a capture date")
    windows = await _windows(db, project_id, body, anchor)
    if windows is None:
        return SuggestOut(windows=None, anchors=0, created=0, queued=0, pairs=[])

    params: dict[str, Any] = {
        "project_id": project_id,
        "min_gap": body.min_gap_days,
        "max_m": body.max_distance_m,
        "model": settings.embedding_model,
        "per_anchor": body.per_anchor,
        "limit": body.limit,
    }
    after_where = _photo_where("endline", windows.endline_from, windows.endline_to, params)
    before_where = _photo_where("baseline", windows.baseline_from, windows.baseline_to, params)
    if body.site_id:
        params["site_id"] = body.site_id
        after_where.append("site_id = :site_id")
        before_where.append("site_id = :site_id")
    if anchor is not None:
        params["anchor_id"] = anchor.id
        after_where.append("id = :anchor_id")
    sql = _CANDIDATES_SQL.format(
        after_where=" AND ".join(after_where), before_where=" AND ".join(before_where)
    )
    rows = (await db.execute(text(sql), params)).mappings().all()

    created = 0
    for row in rows:
        similarity = float(row["similarity"]) if row["similarity"] is not None else None
        result = await db.execute(
            insert(BeforeAfterPair)
            .values(
                organization_id=principal.org_id,
                project_id=project_id,
                site_id=row["site_id"],
                before_asset_id=row["before_id"],
                after_asset_id=row["after_id"],
                status=PairStatus.CANDIDATE,
                origin=PairOrigin.SUGGESTED,
                similarity=similarity,
                distance_m=float(row["distance_m"]) if row["distance_m"] is not None else None,
                days_apart=int(row["days_apart"]),
                rank_score=rules.rank_score(similarity, None),
                created_by_id=principal.user_id,
            )
            .on_conflict_do_nothing(index_elements=["before_asset_id", "after_asset_id"])
            .returning(BeforeAfterPair.id)
        )
        created += len(result.all())
    keys = {(r["before_id"], r["after_id"]) for r in rows}
    pairs: list[BeforeAfterPair] = []
    if keys:
        pairs = list(
            (
                await db.scalars(
                    select(BeforeAfterPair).where(
                        BeforeAfterPair.project_id == project_id,
                        BeforeAfterPair.after_asset_id.in_({a for _, a in keys}),
                        BeforeAfterPair.before_asset_id.in_({b for b, _ in keys}),
                    )
                )
            ).all()
        )
        pairs = [p for p in pairs if (p.before_asset_id, p.after_asset_id) in keys]
    to_queue = [p.id for p in pairs if p.status in {PairStatus.CANDIDATE, PairStatus.FAILED}]
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="before_after.suggested",
        target_type="project",
        target_id=project_id,
        data={"candidates": len(rows), "created": created, "queued": len(to_queue)},
        request_id=rid,
    )
    await db.commit()
    queued = sum(_enqueue(pid) for pid in to_queue)
    ordered = sorted(pairs, key=lambda p: (str(p.after_asset_id), -p.rank_score))
    return SuggestOut(
        windows=Windows(**windows.__dict__),
        anchors=len({p.after_asset_id for p in pairs}),
        created=created,
        queued=queued,
        pairs=await summaries(db, ordered, settings, cloudinary_ready=cloudinary_ready),
    )


def _enqueue(pair_id: uuid.UUID, *, force: bool = False) -> bool:
    try:
        tasks.enqueue(tasks.ANALYZE_PAIR, str(pair_id), *(["1"] if force else []))
        return True
    except Exception as exc:  # the pair is stored; analysis can be requested again
        log.warning("before_after_enqueue_failed", pair_id=str(pair_id), error=str(exc))
        return False


# --- manual pairs & decisions ------------------------------------------------------------------------


async def create_pair(
    db: AsyncSession, principal: Principal, project_id: uuid.UUID, body: PairCreate, rid: str | None
) -> BeforeAfterPair:
    await get_project(db, project_id)
    assets = await _assets(db, {body.before_asset_id, body.after_asset_id})
    before, after = assets.get(body.before_asset_id), assets.get(body.after_asset_id)
    for label, asset in (("before", before), ("after", after)):
        if asset is None or asset.project_id != project_id:
            raise Unprocessable(f"The {label} photo was not found in this project")
        if asset.resource_type != ResourceType.IMAGE:
            raise Unprocessable(f"The {label} item is a video; comparisons use photos")
        if asset.state not in PAIRABLE_STATES:
            raise Unprocessable(f"The {label} photo is '{asset.state.value}' and not processed yet")
    assert before is not None and after is not None
    existing = await db.scalar(
        select(BeforeAfterPair.id).where(
            BeforeAfterPair.before_asset_id == before.id,
            BeforeAfterPair.after_asset_id == after.id,
        )
    )
    if existing is not None:
        raise Conflict("This comparison already exists", details={"pair_id": str(existing)})
    distance = None
    if before.location is not None and after.location is not None:
        distance = await db.scalar(
            text(
                "SELECT ST_Distance(b.location, a.location) FROM assets b, assets a "
                "WHERE b.id = :before AND a.id = :after"
            ),
            {"before": before.id, "after": after.id},
        )
    pair = BeforeAfterPair(
        organization_id=principal.org_id,
        project_id=project_id,
        site_id=after.site_id or before.site_id,
        before_asset_id=before.id,
        after_asset_id=after.id,
        status=PairStatus.CANDIDATE,
        origin=PairOrigin.MANUAL,
        similarity=None,
        distance_m=float(distance) if distance is not None else None,
        days_apart=rules.days_apart(before.capture_time, after.capture_time),
        rank_score=0.0,
        created_by_id=principal.user_id,
    )
    db.add(pair)
    await db.flush()
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="before_after.created",
        target_type="before_after_pair",
        target_id=pair.id,
        data={"before": str(before.id), "after": str(after.id)},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(pair)
    _enqueue(pair.id)
    return pair


async def reanalyze(
    db: AsyncSession, principal: Principal, pair_id: uuid.UUID, rid: str | None
) -> BeforeAfterPair:
    pair = await get_pair(db, pair_id, lock=True)
    if pair.status not in REANALYSABLE:
        raise Conflict(f"A {pair.status.value} comparison cannot be re-analysed")
    audit.record(
        db,
        org_id=pair.organization_id,
        principal=principal,
        action="before_after.reanalysis_requested",
        target_type="before_after_pair",
        target_id=pair.id,
        request_id=rid,
    )
    await db.commit()
    _enqueue(pair.id, force=True)
    return pair


async def _linked_claims(db: AsyncSession, pair_id: uuid.UUID) -> list[Claim]:
    return list(
        (
            await db.scalars(
                select(Claim)
                .join(EvidenceLink, EvidenceLink.claim_id == Claim.id)
                .where(EvidenceLink.pair_id == pair_id)
                .distinct()
            )
        ).all()
    )


async def decide(
    db: AsyncSession,
    principal: Principal,
    pair_id: uuid.UUID,
    target: PairStatus,
    body: PairDecision,
    rid: str | None,
) -> BeforeAfterPair:
    pair = await get_pair(db, pair_id, lock=True)
    note = (body.note or "").strip() or None
    if target == PairStatus.CONFIRMED:
        if pair.status != PairStatus.ANALYZED:
            raise Conflict(
                f"Only analysed comparisons can be confirmed (this one is {pair.status.value})"
            )
        if not (pair.alignment or {}).get("ok") and note is None:
            raise Unprocessable(
                "The photos could not be aligned; confirming needs a note explaining why they "
                "show the same place"
            )
    else:
        if note is None:
            raise Unprocessable("A note is required to reject a comparison")
        if pair.status == PairStatus.REJECTED:
            raise Conflict("This comparison is already rejected")
        linked = await _linked_claims(db, pair.id)
        if linked:
            raise Conflict(
                "Claims use this comparison as evidence; unlink it first",
                details={"claim_ids": [str(c.id) for c in linked]},
            )
    previous = pair.status
    pair.status = target
    pair.decided_by_id, pair.decided_at, pair.decision_note = (
        principal.user_id,
        datetime.now(UTC),
        note,
    )
    audit.record(
        db,
        org_id=pair.organization_id,
        principal=principal,
        action=f"before_after.{target.value}",
        target_type="before_after_pair",
        target_id=pair.id,
        data={"from": previous.value, "note": note, "grade": rules.alignment_grade(pair.alignment)},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(pair)
    return pair


# --- presentation --------------------------------------------------------------------------------------


def _photo(asset: Asset, settings: Settings, *, cloudinary_ready: bool) -> PairPhoto:
    photo = PairPhoto.model_validate(asset)
    photo.thumb_url = thumb_url(asset, settings, cloudinary_ready=cloudinary_ready)
    return photo


def _summary(
    pair: BeforeAfterPair,
    assets: dict[uuid.UUID, Asset],
    settings: Settings,
    *,
    cloudinary_ready: bool,
) -> dict[str, Any]:
    changes = pair.changes or {}
    analysed = pair.alignment is not None
    return {
        "id": pair.id,
        "project_id": pair.project_id,
        "site_id": pair.site_id,
        "status": pair.status,
        "origin": pair.origin,
        "before": _photo(assets[pair.before_asset_id], settings, cloudinary_ready=cloudinary_ready),
        "after": _photo(assets[pair.after_asset_id], settings, cloudinary_ready=cloudinary_ready),
        "similarity": pair.similarity,
        "distance_m": pair.distance_m,
        "days_apart": pair.days_apart,
        "rank_score": pair.rank_score,
        "alignment_grade": rules.alignment_grade(pair.alignment) if analysed else None,
        "change_summary": pair.change_summary,
        "changed_share": changes.get("changed_share"),
        "green_delta_pp": changes.get("green_delta_pp"),
        "limitation_count": len(pair.limitations or []),
        "analysis_error": pair.analysis_error,
        "decided_at": pair.decided_at,
        "created_at": pair.created_at,
    }


async def summaries(
    db: AsyncSession, pairs: list[BeforeAfterPair], settings: Settings, *, cloudinary_ready: bool
) -> list[PairSummary]:
    assets = await _assets(
        db, {p.before_asset_id for p in pairs} | {p.after_asset_id for p in pairs}
    )
    return [
        PairSummary(**_summary(p, assets, settings, cloudinary_ready=cloudinary_ready))
        for p in pairs
    ]


async def list_pairs(
    db: AsyncSession,
    project_id: uuid.UUID,
    settings: Settings,
    *,
    cloudinary_ready: bool,
    status: PairStatus | None,
    site_id: uuid.UUID | None,
    asset_id: uuid.UUID | None,
    limit: int,
) -> list[PairSummary]:
    await get_project(db, project_id)
    query = select(BeforeAfterPair).where(BeforeAfterPair.project_id == project_id)
    if status:
        query = query.where(BeforeAfterPair.status == status)
    if site_id:
        query = query.where(BeforeAfterPair.site_id == site_id)
    if asset_id:
        query = query.where(
            or_(
                BeforeAfterPair.before_asset_id == asset_id,
                BeforeAfterPair.after_asset_id == asset_id,
            )
        )
    pairs = list(
        (
            await db.scalars(
                query.order_by(
                    BeforeAfterPair.after_asset_id,
                    BeforeAfterPair.rank_score.desc(),
                    BeforeAfterPair.created_at,
                ).limit(limit)
            )
        ).all()
    )
    return await summaries(db, pairs, settings, cloudinary_ready=cloudinary_ready)


def composite_link(pair: BeforeAfterPair, before: Asset, *, public: bool) -> str | None:
    raw = pair.public_composite_transformation if public else pair.composite_transformation
    if not raw:
        return None
    variant = "before_after_public" if public else "before_after"
    return signed_url(before.public_id, raw, variant=variant).url


async def pair_detail(
    db: AsyncSession, pair: BeforeAfterPair, settings: Settings, *, cloudinary_ready: bool
) -> PairDetail:
    assets = await _assets(db, {pair.before_asset_id, pair.after_asset_id})
    before, after = assets[pair.before_asset_id], assets[pair.after_asset_id]
    named = settings.cloudinary_use_named_transformations

    def review(asset: Asset) -> str | None:
        if not cloudinary_ready:
            return None
        return rendition_url(asset.public_id, "image", "review", use_named=named).url

    return PairDetail(
        **_summary(pair, assets, settings, cloudinary_ready=cloudinary_ready),
        alignment=pair.alignment,
        changes=pair.changes,
        limitations=list(pair.limitations or []),
        analysis_version=pair.analysis_version,
        analyzed_at=pair.analyzed_at,
        before_url=review(before),
        after_url=review(after),
        composite_url=composite_link(pair, before, public=False) if cloudinary_ready else None,
        composite_transformation=pair.composite_transformation,
        public_composite_url=composite_link(pair, before, public=True)
        if cloudinary_ready
        else None,
        public_composite_transformation=pair.public_composite_transformation,
        created_by_id=pair.created_by_id,
        decided_by_id=pair.decided_by_id,
        decision_note=pair.decision_note,
        claims=[
            PairClaimRef(id=c.id, statement=c.statement, status=c.status)
            for c in await _linked_claims(db, pair.id)
        ],
    )
