"""Analyse a before/after pair: geometric verification, alignment, visible change, limitations and
the Cloudinary composite (with lineage).

Both photos are read through the same `ev_ai` rendition the vision models use (bounded JPEG, the
fetch is recorded as a derivative). The result is idempotent per ANALYSIS_VERSION: re-running only
recomputes when forced or when the algorithm version changed. Human decisions are never touched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from celery import Task
from evidentia_cloudinary.composite import Side, composite_transformation
from evidentia_core import tasks
from evidentia_core.db.models import Asset, AuditEvent, BeforeAfterPair, Derivative
from evidentia_core.db.session import set_session_tenant, sync_system_session
from evidentia_core.domain import before_after as rules
from evidentia_core.domain.enums import ActorKind, PairStatus
from evidentia_core.events import build_event
from evidentia_ml.before_after import (
    ANALYSIS_VERSION,
    ImageDecodeError,
    PairAnalysis,
    analyze_pair_bytes,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from evidentia_worker.celery_app import app
from evidentia_worker.context import WorkerContext, get_context
from evidentia_worker.errors import TRANSIENT_EXCEPTIONS, PermanentError
from evidentia_worker.pipeline.enrichment import model_input

log = structlog.get_logger("evidentia.before_after")
MAX_RETRIES = 4
DECIDED = (PairStatus.CONFIRMED, PairStatus.REJECTED)


def _facts(asset: Asset) -> rules.PhotoFacts:
    return rules.PhotoFacts(
        capture_time=asset.capture_time,
        capture_time_source=asset.capture_time_source.value,
        has_location=asset.latitude is not None and asset.longitude is not None,
        width=asset.width,
        height=asset.height,
        quality_score=asset.quality_score,
    )


def _label(kind: str, asset: Asset) -> str:
    when = (
        asset.capture_time.strftime("%d %b %Y").lstrip("0")
        if asset.capture_time
        else "date unknown"
    )
    return f"{kind} {when}"


def _box(alignment: dict[str, object], key: str) -> tuple[float, float, float, float]:
    raw = alignment.get(key) if alignment.get("ok") else None
    if not isinstance(raw, list) or len(raw) != 4:
        return (0.0, 0.0, 1.0, 1.0)
    x, y, w, h = (float(v) for v in raw)
    return (x, y, w, h)


def _record_derivative(session: Session, pair: BeforeAfterPair, purpose: str, raw: str) -> None:
    exists = session.scalar(
        select(Derivative.id).where(
            Derivative.asset_id == pair.before_asset_id,
            Derivative.purpose == purpose,
            Derivative.transformation == raw,
        )
    )
    if exists is None:
        session.add(
            Derivative(
                organization_id=pair.organization_id,
                asset_id=pair.before_asset_id,
                purpose=purpose,
                transformation=raw,
                format="jpg",
                source="on_demand",
                generative=False,
            )
        )


def record_analysis(
    session: Session, pair: BeforeAfterPair, before: Asset, after: Asset, result: PairAnalysis
) -> None:
    """Store measurements, rule-derived limitations, ranking and composite lineage on the pair."""
    data = result.as_dict()
    alignment, change = data["alignment"], data["change"]
    pair.alignment = {
        **alignment,
        "before_size": data["before_size"],
        "after_size": data["after_size"],
    }
    pair.changes = change
    pair.change_summary = rules.change_summary(change, alignment)
    pair.limitations = rules.derive_limitations(
        alignment, change, _facts(before), _facts(after), pair.distance_m
    )
    pair.rank_score = rules.rank_score(pair.similarity, alignment)
    pair.analysis_version = result.version
    pair.analysis_error = None
    pair.analyzed_at = datetime.now(UTC)
    pair.status = PairStatus.ANALYZED

    before_side = Side(before.public_id, _box(alignment, "before_box"), _label("BEFORE", before))
    after_side = Side(after.public_id, _box(alignment, "after_box"), _label("AFTER", after))
    pair.composite_transformation = composite_transformation(before_side, after_side)
    pair.public_composite_transformation = composite_transformation(
        before_side, after_side, redact=True
    )
    _record_derivative(session, pair, "before_after", pair.composite_transformation)
    _record_derivative(session, pair, "before_after_public", pair.public_composite_transformation)
    session.add(
        AuditEvent(
            organization_id=pair.organization_id,
            actor_kind=ActorKind.SYSTEM,
            action="before_after.analyzed",
            target_type="before_after_pair",
            target_id=pair.id,
            data={
                "version": result.version,
                "aligned": alignment["ok"],
                "inliers": alignment["inliers"],
                "rank_score": pair.rank_score,
            },
        )
    )


def _publish(ctx: WorkerContext, pair: BeforeAfterPair) -> None:
    ctx.publisher.publish(
        pair.organization_id,
        build_event(
            "before_after.updated",
            pair_id=pair.id,
            project_id=pair.project_id,
            after_asset_id=pair.after_asset_id,
            status=pair.status.value,
        ),
    )


def _fail(session: Session, ctx: WorkerContext, pair: BeforeAfterPair, error: str) -> str:
    pair.status = PairStatus.FAILED
    pair.analysis_error = error[:1000]
    session.commit()
    _publish(ctx, pair)
    log.warning("before_after_failed", pair_id=str(pair.id), error=error)
    return "failed"


@app.task(name=tasks.ANALYZE_PAIR, bind=True, max_retries=MAX_RETRIES)
def analyze_pair(self: Task, pair_id: str, force: bool = False) -> str:
    ctx = get_context()
    with sync_system_session() as session:
        pair = session.get(BeforeAfterPair, uuid.UUID(pair_id))
        if pair is None:
            return "missing"
        set_session_tenant(session, pair.organization_id)
        if pair.status in DECIDED:
            return "decided"
        if (
            pair.status == PairStatus.ANALYZED
            and pair.analysis_version == ANALYSIS_VERSION
            and not force
        ):
            return "analyzed"
        before = session.get(Asset, pair.before_asset_id)
        after = session.get(Asset, pair.after_asset_id)
        assert before is not None and after is not None  # FKs
        if ctx.creds is None:
            return _fail(session, ctx, pair, "Cloudinary is not configured (CLOUDINARY_URL)")

        pair.status = PairStatus.ANALYZING
        session.commit()
        _publish(ctx, pair)
        try:
            before_bytes = model_input(session, before, ctx).data
            after_bytes = model_input(session, after, ctx).data
            result = analyze_pair_bytes(before_bytes, after_bytes)
        except PermanentError as exc:
            return _fail(session, ctx, pair, str(exc))
        except ImageDecodeError as exc:
            return _fail(session, ctx, pair, f"Could not decode a photo: {exc}")
        except TRANSIENT_EXCEPTIONS as exc:
            if self.request.retries >= MAX_RETRIES:
                return _fail(session, ctx, pair, f"gave up after retries: {exc}")
            raise self.retry(countdown=30 * 2**self.request.retries) from exc

        record_analysis(session, pair, before, after, result)
        session.commit()
        _publish(ctx, pair)
        log.info(
            "before_after_analyzed",
            pair_id=pair_id,
            aligned=result.alignment.ok,
            inliers=result.alignment.inliers,
            rank_score=pair.rank_score,
        )
        return "analyzed"
