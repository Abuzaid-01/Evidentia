"""Claims, metrics and the evidence graph.

Workflow: DRAFT -> IN_REVIEW -> APPROVED | REJECTED (-> DRAFT) ; APPROVED -> RETRACTED.
* Evidence and metrics can only change while a claim is DRAFT or REJECTED.
* Deterministic rules (domain/claims.py) gate submit and approve.
* Approval needs a validation run (LLM or `not_checked`), a different person than the author
  (four-eyes; admins exempt), and an explicit override note if the LLM said `not_supported`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

import anyio
from evidentia_ai.claim_validator import EvidenceItem, MetricItem, validate_claim
from evidentia_ai.text_llm import TextLLM
from evidentia_core.config import Settings
from evidentia_core.db.models import (
    ActivityEvent,
    Asset,
    BeforeAfterPair,
    Claim,
    ClaimMetric,
    Derivative,
    EvidenceLink,
    Metric,
    Observation,
    Project,
    Site,
    Taxonomy,
)
from evidentia_core.domain.claims import (
    EvidenceFact,
    MetricFact,
    can_move,
    check_rules,
    support_level,
)
from evidentia_core.domain.enums import (
    AssetState,
    ClaimStatus,
    EvidenceRelation,
    EvidenceTarget,
    ObservationStatus,
    OntologyType,
    PairStatus,
    Role,
    ValidationVerdict,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.errors import Conflict, Forbidden, NotFound, Unprocessable
from evidentia_api.schemas.claims import (
    ClaimCreate,
    ClaimDetail,
    ClaimOut,
    ClaimUpdate,
    DecisionBody,
    EventCreate,
    EventOut,
    EventSuggestion,
    EvidenceGraph,
    EvidenceLinkCreate,
    EvidenceLinkOut,
    GraphEdge,
    GraphNode,
    MetricCreate,
    MetricOut,
)
from evidentia_api.services import audit
from evidentia_api.services.assets import thumb_url
from evidentia_api.services.projects import get_project, get_site

EDITABLE = {ClaimStatus.DRAFT, ClaimStatus.REJECTED}
LINKABLE_ASSET_STATES = {AssetState.READY, AssetState.REVIEW_REQUIRED}


# --- helpers -------------------------------------------------------------------------------------


async def get_claim(db: AsyncSession, claim_id: uuid.UUID, *, lock: bool = False) -> Claim:
    query = select(Claim).where(Claim.id == claim_id)
    claim = await db.scalar(query.with_for_update() if lock else query)
    if claim is None:
        raise NotFound("Claim not found")
    return claim


def _require_editable(claim: Claim) -> None:
    if claim.status not in EDITABLE:
        raise Conflict(
            f"Claim is '{claim.status.value}'; evidence can only change on draft or rejected claims"
        )


def _obs_summary(obs: Observation) -> str:
    conf = f", confidence {obs.confidence:.2f}" if obs.confidence is not None else ""
    return f"{obs.ontology_type.value} '{obs.subject.replace('_', ' ')}' {obs.predicate} ({obs.status.value}{conf})"


def _pair_summary(pair: BeforeAfterPair, before: Asset | None, after: Asset | None) -> str:
    def when(asset: Asset | None) -> str:
        if asset is None or asset.capture_time is None:
            return "unknown date"
        return asset.capture_time.date().isoformat()

    grade = "aligned" if (pair.alignment or {}).get("ok") else "not aligned"
    return (
        f"before/after comparison ({pair.status.value}, {grade}): {when(before)} to {when(after)}; "
        f"{pair.change_summary or 'change not measured'}"
    )


async def _pairs(db: AsyncSession, links: list[EvidenceLink]) -> dict[uuid.UUID, BeforeAfterPair]:
    ids = [lk.pair_id for lk in links if lk.pair_id]
    if not ids:
        return {}
    rows = await db.scalars(select(BeforeAfterPair).where(BeforeAfterPair.id.in_(ids)))
    return {p.id: p for p in rows.all()}


async def _links(db: AsyncSession, claim_id: uuid.UUID) -> list[EvidenceLink]:
    return list(
        (
            await db.scalars(
                select(EvidenceLink)
                .where(EvidenceLink.claim_id == claim_id)
                .order_by(EvidenceLink.created_at)
            )
        ).all()
    )


async def _metrics(db: AsyncSession, claim_id: uuid.UUID) -> list[Metric]:
    return list(
        (
            await db.scalars(
                select(Metric)
                .join(ClaimMetric, ClaimMetric.metric_id == Metric.id)
                .where(ClaimMetric.claim_id == claim_id)
            )
        ).all()
    )


async def evaluate(db: AsyncSession, claim: Claim) -> None:
    """Recompute deterministic rules + support level (call after any change to the claim)."""
    links = await _links(db, claim.id)
    obs_ids = [link.observation_id for link in links if link.observation_id]
    observations = {
        o.id: o
        for o in (await db.scalars(select(Observation).where(Observation.id.in_(obs_ids)))).all()
    }
    assets = {
        a.id: a
        for a in (
            await db.scalars(select(Asset).where(Asset.id.in_([link.asset_id for link in links])))
        ).all()
    }
    pairs = await _pairs(db, links)
    facts = []
    for link in links:
        if link.pair_id:  # a before/after comparison counts once a reviewer confirmed it
            pair = pairs.get(link.pair_id)
            verified = pair is not None and pair.status == PairStatus.CONFIRMED
        elif link.observation_id:
            obs = observations.get(link.observation_id)
            verified = obs is not None and obs.status == ObservationStatus.VERIFIED
        else:  # asset-level link: counts only once a human has reviewed the asset
            asset = assets.get(link.asset_id)
            verified = asset is not None and asset.reviewed_at is not None
        facts.append(EvidenceFact(link.relation.value, verified))
    metrics = [
        MetricFact(Decimal(m.value), bool(m.source_reference and m.source_type))
        for m in await _metrics(db, claim.id)
    ]
    rules = check_rules(claim.claim_type, claim.statement, facts, metrics)
    claim.rule_check = rules.as_dict()
    claim.support_level = support_level(claim.status, rules, claim.validation_verdict)


def _invalidate_validation(claim: Claim) -> None:
    claim.validation, claim.validation_verdict, claim.validated_at = None, None, None


# --- metrics ---------------------------------------------------------------------------------------


async def create_metric(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    body: MetricCreate,
    rid: str | None,
) -> Metric:
    await get_project(db, project_id)
    if body.site_id and (await get_site(db, body.site_id)).project_id != project_id:
        raise Unprocessable("Site does not belong to this project")
    metric = Metric(
        organization_id=principal.org_id,
        project_id=project_id,
        created_by_id=principal.user_id,
        **body.model_dump(),
    )
    db.add(metric)
    await db.flush()
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="metric.created",
        target_type="metric",
        target_id=metric.id,
        data={"name": metric.name, "value": str(metric.value), "source": body.source_type.value},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(metric)
    return metric


# --- claims ------------------------------------------------------------------------------------------


async def create_claim(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    body: ClaimCreate,
    rid: str | None,
) -> Claim:
    await get_project(db, project_id)
    if body.site_id and (await get_site(db, body.site_id)).project_id != project_id:
        raise Unprocessable("Site does not belong to this project")
    if body.supersedes_id:
        old = await get_claim(db, body.supersedes_id)
        if old.project_id != project_id:
            raise Unprocessable("Superseded claim belongs to another project")
    claim = Claim(
        organization_id=principal.org_id,
        project_id=project_id,
        created_by_id=principal.user_id,
        **body.model_dump(),
    )
    db.add(claim)
    await db.flush()
    await evaluate(db, claim)
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="claim.created",
        target_type="claim",
        target_id=claim.id,
        data={"type": claim.claim_type.value, "statement": claim.statement},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(claim)
    return claim


async def update_claim(
    db: AsyncSession, principal: Principal, claim_id: uuid.UUID, body: ClaimUpdate, rid: str | None
) -> Claim:
    claim = await get_claim(db, claim_id, lock=True)
    _require_editable(claim)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(claim, field, value)
    if claim.status == ClaimStatus.REJECTED:
        claim.status = ClaimStatus.DRAFT  # editing a rejected claim reopens it
    _invalidate_validation(claim)
    await evaluate(db, claim)
    audit.record(
        db,
        org_id=claim.organization_id,
        principal=principal,
        action="claim.updated",
        target_type="claim",
        target_id=claim.id,
        data={k: str(v) for k, v in changes.items()},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(claim)
    return claim


async def add_evidence(
    db: AsyncSession,
    principal: Principal,
    claim_id: uuid.UUID,
    body: EvidenceLinkCreate,
    rid: str | None,
) -> EvidenceLink:
    claim = await get_claim(db, claim_id, lock=True)
    _require_editable(claim)
    pair = None
    asset_id = body.asset_id
    if body.pair_id:
        pair = await db.get(BeforeAfterPair, body.pair_id)
        if pair is None or pair.project_id != claim.project_id:
            raise Unprocessable("Before/after comparison not found in this claim's project")
        if pair.status != PairStatus.CONFIRMED:
            raise Unprocessable(
                f"Comparison is '{pair.status.value}'; a reviewer must confirm it before it can "
                "be used as evidence"
            )
        if asset_id not in (None, pair.before_asset_id, pair.after_asset_id):
            raise Unprocessable("asset_id must be one of the comparison's photos")
        asset_id = pair.after_asset_id
    asset = await db.get(Asset, asset_id)
    if asset is None or asset.project_id != claim.project_id:
        raise Unprocessable("Asset not found in this claim's project")
    if asset.state not in LINKABLE_ASSET_STATES:
        raise Unprocessable(f"Asset is '{asset.state.value}' and cannot be used as evidence yet")
    if (asset.flags or {}).get("generative"):
        raise Unprocessable(
            "Generative or campaign-enhanced media cannot be attached to claims as evidence"
        )
    if body.derivative_id:
        deriv = await db.get(Derivative, body.derivative_id)
        if deriv is None or deriv.asset_id != asset.id:
            raise Unprocessable("Derivative not found for this asset")
        if deriv.generative:
            raise Unprocessable(
                "Generative or campaign-enhanced media cannot be attached to claims as evidence"
            )
    obs = None
    if body.observation_id:
        obs = await db.get(Observation, body.observation_id)
        if obs is None or obs.asset_id != asset.id:
            raise Unprocessable("Observation does not belong to this asset")
        if obs.status in {ObservationStatus.SUPERSEDED, ObservationStatus.REJECTED}:
            raise Unprocessable(
                f"Observation is '{obs.status.value}'; link its replacement instead"
            )
    span = body.span
    if span is None and obs is not None:
        evidence_span = obs.evidence_span or {}
        start = evidence_span.get("start_ms")
        end = evidence_span.get("end_ms")
        if (
            evidence_span.get("type") == "segment"
            and isinstance(start, int)
            and isinstance(end, int)
        ):
            span = {"type": "segment", "start_ms": start, "end_ms": end}
    duplicate = await db.scalar(
        select(func.count())
        .select_from(EvidenceLink)
        .where(
            EvidenceLink.claim_id == claim.id,
            EvidenceLink.asset_id == asset.id,
            EvidenceLink.observation_id.is_(None)
            if body.observation_id is None
            else EvidenceLink.observation_id == body.observation_id,
            EvidenceLink.pair_id.is_(None)
            if body.pair_id is None
            else EvidenceLink.pair_id == body.pair_id,
        )
    )
    if duplicate:
        raise Conflict("This evidence is already linked to the claim")
    link = EvidenceLink(
        organization_id=claim.organization_id,
        target_type=EvidenceTarget.CLAIM,
        target_id=claim.id,
        claim_id=claim.id,
        asset_id=asset.id,
        observation_id=body.observation_id,
        pair_id=body.pair_id,
        relation=body.relation,
        span=span,
        note=body.note,
        created_by_id=principal.user_id,
    )
    db.add(link)
    await db.flush()
    _invalidate_validation(claim)
    await evaluate(db, claim)
    audit.record(
        db,
        org_id=claim.organization_id,
        principal=principal,
        action="claim.evidence_linked",
        target_type="claim",
        target_id=claim.id,
        data={
            "link_id": str(link.id),
            "asset_id": str(asset.id),
            "observation_id": str(body.observation_id) if body.observation_id else None,
            "pair_id": str(body.pair_id) if body.pair_id else None,
            "relation": body.relation.value,
        },
        request_id=rid,
    )
    await db.commit()
    await db.refresh(link)
    return link


async def remove_evidence(
    db: AsyncSession, principal: Principal, claim_id: uuid.UUID, link_id: uuid.UUID, rid: str | None
) -> None:
    claim = await get_claim(db, claim_id, lock=True)
    _require_editable(claim)
    link = await db.get(EvidenceLink, link_id)
    if link is None or link.claim_id != claim.id:
        raise NotFound("Evidence link not found on this claim")
    await db.delete(link)
    await db.flush()
    _invalidate_validation(claim)
    await evaluate(db, claim)
    audit.record(
        db,
        org_id=claim.organization_id,
        principal=principal,
        action="claim.evidence_unlinked",
        target_type="claim",
        target_id=claim.id,
        data={"link_id": str(link_id)},
        request_id=rid,
    )
    await db.commit()


async def set_metric_link(
    db: AsyncSession,
    principal: Principal,
    claim_id: uuid.UUID,
    metric_id: uuid.UUID,
    *,
    linked: bool,
    rid: str | None,
) -> None:
    claim = await get_claim(db, claim_id, lock=True)
    _require_editable(claim)
    metric = await db.get(Metric, metric_id)
    if metric is None or metric.project_id != claim.project_id:
        raise Unprocessable("Metric not found in this claim's project")
    existing = await db.scalar(
        select(ClaimMetric).where(
            ClaimMetric.claim_id == claim.id, ClaimMetric.metric_id == metric.id
        )
    )
    if linked and existing is None:
        db.add(
            ClaimMetric(
                organization_id=claim.organization_id, claim_id=claim.id, metric_id=metric.id
            )
        )
    elif not linked and existing is not None:
        await db.delete(existing)
    await db.flush()
    _invalidate_validation(claim)
    await evaluate(db, claim)
    audit.record(
        db,
        org_id=claim.organization_id,
        principal=principal,
        action="claim.metric_linked" if linked else "claim.metric_unlinked",
        target_type="claim",
        target_id=claim.id,
        data={"metric_id": str(metric.id)},
        request_id=rid,
    )
    await db.commit()


async def _validation_inputs(
    db: AsyncSession, claim: Claim
) -> tuple[list[EvidenceItem], list[MetricItem]]:
    links = await _links(db, claim.id)
    observations = {
        o.id: o
        for o in (
            await db.scalars(
                select(Observation).where(
                    Observation.id.in_([lk.observation_id for lk in links if lk.observation_id])
                )
            )
        ).all()
    }
    assets = {
        a.id: a
        for a in (
            await db.scalars(select(Asset).where(Asset.id.in_([lk.asset_id for lk in links])))
        ).all()
    }
    sites = {
        s.id: s.name
        for s in (await db.scalars(select(Site).where(Site.project_id == claim.project_id))).all()
    }
    pairs = await _pairs(db, links)
    pair_assets = {
        a.id: a
        for a in (
            await db.scalars(
                select(Asset).where(Asset.id.in_([p.before_asset_id for p in pairs.values()]))
            )
        ).all()
    } | assets
    items = []
    for link in links:
        asset = assets[link.asset_id]
        where = sites.get(asset.site_id) if asset.site_id else None
        when = asset.capture_time.date().isoformat() if asset.capture_time else "unknown date"
        context = (
            f"media '{asset.original_filename}' captured {when} ({asset.capture_time_source.value})"
            + (f" at {where}" if where else "")
        )
        if link.pair_id and link.pair_id in pairs:
            pair = pairs[link.pair_id]
            what = _pair_summary(
                pair, pair_assets.get(pair.before_asset_id), pair_assets.get(pair.after_asset_id)
            )
        elif link.observation_id and link.observation_id in observations:
            what = _obs_summary(observations[link.observation_id])
        else:
            verified = ", ".join(asset.verified_activities or []) or "none"
            what = f"asset caption: {asset.caption or 'n/a'}; verified activities: {verified}; reviewed: {bool(asset.reviewed_at)}"
        items.append(
            EvidenceItem(
                id=str(link.id), relation=link.relation.value, description=f"{what}; {context}"
            )
        )
    metrics = [
        MetricItem(
            id=str(m.id),
            description=f"{m.name} = {m.value.normalize() if isinstance(m.value, Decimal) else m.value} {m.unit or ''} "
            f"({m.source_type.value}: {m.source_reference}; method: {m.method})",
        )
        for m in await _metrics(db, claim.id)
    ]
    return items, metrics


async def validate(
    db: AsyncSession,
    principal: Principal,
    claim_id: uuid.UUID,
    llms: list[TextLLM],
    rid: str | None,
) -> Claim:
    claim = await get_claim(db, claim_id, lock=True)
    if claim.status in {ClaimStatus.APPROVED, ClaimStatus.RETRACTED}:
        raise Conflict("Approved or retracted claims are frozen")
    await evaluate(db, claim)
    evidence, metrics = await _validation_inputs(db, claim)
    statement, claim_type = claim.statement, claim.claim_type.value
    result = await anyio.to_thread.run_sync(
        lambda: validate_claim(statement, claim_type, evidence, metrics, llms)
    )
    claim.validation, claim.validation_verdict, claim.validated_at = (
        result.details,
        result.verdict,
        datetime.now(UTC),
    )
    await evaluate(db, claim)
    audit.record(
        db,
        org_id=claim.organization_id,
        principal=principal,
        action="claim.validated",
        target_type="claim",
        target_id=claim.id,
        data={
            "verdict": result.verdict.value,
            "rules_passed": claim.rule_check["passed"] if claim.rule_check else None,
        },
        request_id=rid,
    )
    await db.commit()
    await db.refresh(claim)
    return claim


async def transition(
    db: AsyncSession,
    principal: Principal,
    claim_id: uuid.UUID,
    target: ClaimStatus,
    body: DecisionBody,
    rid: str | None,
) -> Claim:
    claim = await get_claim(db, claim_id, lock=True)
    if not can_move(claim.status, target):
        raise Conflict(f"Cannot move a '{claim.status.value}' claim to '{target.value}'")
    await evaluate(db, claim)
    rules_ok = bool(claim.rule_check and claim.rule_check.get("passed"))

    if target == ClaimStatus.IN_REVIEW and not rules_ok:
        raise Unprocessable("Claim does not meet the evidence rules yet", details=claim.rule_check)
    if target == ClaimStatus.APPROVED:
        principal.require(Role.REVIEWER)
        if claim.created_by_id == principal.user_id and principal.role != Role.ADMIN:
            raise Forbidden("Four-eyes rule: someone other than the author must approve this claim")
        if not rules_ok:
            raise Unprocessable("Claim does not meet the evidence rules", details=claim.rule_check)
        if claim.validated_at is None:
            raise Unprocessable("Run validation before approving")
        if claim.validation_verdict == ValidationVerdict.NOT_SUPPORTED and not body.override:
            raise Unprocessable(
                "Validation says not_supported: fix the claim or approve with override + note"
            )
    if target in {ClaimStatus.REJECTED, ClaimStatus.RETRACTED} and not (
        body.note and body.note.strip()
    ):
        raise Unprocessable(f"A note is required to mark a claim {target.value}")
    if target == ClaimStatus.RETRACTED:
        principal.require(Role.MANAGER)

    previous = claim.status
    claim.status = target
    if target in {ClaimStatus.APPROVED, ClaimStatus.REJECTED, ClaimStatus.RETRACTED}:
        claim.decided_by_id, claim.decided_at, claim.decision_note = (
            principal.user_id,
            datetime.now(UTC),
            body.note,
        )
    await evaluate(db, claim)
    audit.record(
        db,
        org_id=claim.organization_id,
        principal=principal,
        action=f"claim.{target.value}",
        target_type="claim",
        target_id=claim.id,
        data={
            "from": previous.value,
            "note": body.note,
            "override": body.override,
            "verdict": claim.validation_verdict.value if claim.validation_verdict else None,
        },
        request_id=rid,
    )
    await db.commit()
    await db.refresh(claim)
    return claim


async def claim_detail(
    db: AsyncSession, claim: Claim, settings: Settings, *, cloudinary_ready: bool
) -> ClaimDetail:
    links = await _links(db, claim.id)
    observations = {
        o.id: o
        for o in (
            await db.scalars(
                select(Observation).where(
                    Observation.id.in_([lk.observation_id for lk in links if lk.observation_id])
                )
            )
        ).all()
    }
    assets = {
        a.id: a
        for a in (
            await db.scalars(select(Asset).where(Asset.id.in_([lk.asset_id for lk in links])))
        ).all()
    }
    pairs = await _pairs(db, links)
    befores = {
        a.id: a
        for a in (
            await db.scalars(
                select(Asset).where(Asset.id.in_([p.before_asset_id for p in pairs.values()]))
            )
        ).all()
    }
    evidence = []
    for link in links:
        asset = assets[link.asset_id]
        obs = observations.get(link.observation_id) if link.observation_id else None
        pair = pairs.get(link.pair_id) if link.pair_id else None
        out = EvidenceLinkOut.model_validate(link)
        if pair is not None:
            out.verified = pair.status == PairStatus.CONFIRMED
            out.pair_summary = _pair_summary(pair, befores.get(pair.before_asset_id), asset)
        else:
            out.verified = (
                (obs.status == ObservationStatus.VERIFIED) if obs else asset.reviewed_at is not None
            )
        out.observation_summary = _obs_summary(obs) if obs else None
        out.asset_caption = asset.caption
        out.thumb_url = thumb_url(asset, settings, cloudinary_ready=cloudinary_ready)
        evidence.append(out)
    return ClaimDetail(
        **ClaimOut.model_validate(claim).model_dump(),
        evidence=evidence,
        metrics=[MetricOut.model_validate(m) for m in await _metrics(db, claim.id)],
    )


async def claim_graph(db: AsyncSession, claim: Claim) -> EvidenceGraph:
    """claim <- evidence_link <- observation <- asset ; claim <- metric."""
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    cid = f"claim:{claim.id}"
    nodes[cid] = GraphNode(
        id=cid,
        type="claim",
        label=claim.statement[:120],
        data={"status": claim.status.value, "support_level": claim.support_level.value},
    )
    links = await _links(db, claim.id)
    observations = {
        o.id: o
        for o in (
            await db.scalars(
                select(Observation).where(
                    Observation.id.in_([lk.observation_id for lk in links if lk.observation_id])
                )
            )
        ).all()
    }
    assets = {
        a.id: a
        for a in (
            await db.scalars(select(Asset).where(Asset.id.in_([lk.asset_id for lk in links])))
        ).all()
    }
    pairs = await _pairs(db, links)
    befores = {
        a.id: a
        for a in (
            await db.scalars(
                select(Asset).where(Asset.id.in_([p.before_asset_id for p in pairs.values()]))
            )
        ).all()
    }
    for link in links:
        asset = assets[link.asset_id]
        aid = f"asset:{asset.id}"
        nodes.setdefault(
            aid,
            GraphNode(
                id=aid,
                type="asset",
                label=asset.original_filename or str(asset.id),
                data={
                    "public_id": asset.public_id,
                    "capture_time": asset.capture_time.isoformat() if asset.capture_time else None,
                },
            ),
        )
        if link.pair_id and link.pair_id in pairs:
            pair = pairs[link.pair_id]
            before = befores.get(pair.before_asset_id)
            pid = f"pair:{pair.id}"
            bid = f"asset:{pair.before_asset_id}"
            if before is not None:
                nodes.setdefault(
                    bid,
                    GraphNode(
                        id=bid,
                        type="asset",
                        label=before.original_filename or str(before.id),
                        data={
                            "public_id": before.public_id,
                            "capture_time": before.capture_time.isoformat()
                            if before.capture_time
                            else None,
                        },
                    ),
                )
            nodes.setdefault(
                pid,
                GraphNode(
                    id=pid,
                    type="before_after",
                    label=_pair_summary(pair, before, asset),
                    data={
                        "status": pair.status.value,
                        "composite_transformation": pair.composite_transformation,
                    },
                ),
            )
            edges.append(GraphEdge(source=bid, target=pid, relation="before"))
            edges.append(GraphEdge(source=aid, target=pid, relation="after"))
            edges.append(GraphEdge(source=pid, target=cid, relation=link.relation.value))
        elif link.observation_id and link.observation_id in observations:
            obs = observations[link.observation_id]
            oid = f"observation:{obs.id}"
            nodes.setdefault(
                oid,
                GraphNode(
                    id=oid,
                    type="observation",
                    label=_obs_summary(obs),
                    data={"status": obs.status.value},
                ),
            )
            edges.append(GraphEdge(source=aid, target=oid, relation="observed_in"))
            edges.append(GraphEdge(source=oid, target=cid, relation=link.relation.value))
        else:
            edges.append(GraphEdge(source=aid, target=cid, relation=link.relation.value))
    for metric in await _metrics(db, claim.id):
        mid = f"metric:{metric.id}"
        nodes[mid] = GraphNode(
            id=mid,
            type="metric",
            label=f"{metric.name} = {metric.value} {metric.unit or ''}".strip(),
            data={
                "source_type": metric.source_type.value,
                "source_reference": metric.source_reference,
            },
        )
        edges.append(GraphEdge(source=mid, target=cid, relation="measures"))
    return EvidenceGraph(nodes=list(nodes.values()), edges=edges)


# --- activity events ------------------------------------------------------------------------------


async def create_event(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    body: EventCreate,
    rid: str | None,
) -> EventOut:
    project = await get_project(db, project_id)
    taxonomy = await db.scalar(
        select(Taxonomy).where(
            Taxonomy.project_id == project.id, Taxonomy.version == project.active_taxonomy_version
        )
    )
    if body.activity not in {a["key"] for a in (taxonomy.activities if taxonomy else [])}:
        raise Unprocessable(f"'{body.activity}' is not an activity in this project")
    if body.site_id and (await get_site(db, body.site_id)).project_id != project_id:
        raise Unprocessable("Site does not belong to this project")
    event = ActivityEvent(
        organization_id=principal.org_id,
        project_id=project_id,
        created_by_id=principal.user_id,
        **body.model_dump(exclude={"asset_ids"}),
    )
    db.add(event)
    await db.flush()
    assets = (
        await db.scalars(
            select(Asset).where(Asset.id.in_(body.asset_ids), Asset.project_id == project_id)
        )
    ).all()
    if len(assets) != len(set(body.asset_ids)):
        raise Unprocessable("Some assets were not found in this project")
    for asset in assets:
        db.add(
            EvidenceLink(
                organization_id=principal.org_id,
                target_type=EvidenceTarget.EVENT,
                target_id=event.id,
                event_id=event.id,
                asset_id=asset.id,
                relation=EvidenceRelation.SUPPORTS,
                created_by_id=principal.user_id,
            )
        )
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="event.created",
        target_type="event",
        target_id=event.id,
        data={"activity": body.activity, "assets": len(assets)},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(event)
    out = EventOut.model_validate(event)
    out.evidence_count = len(assets)
    return out


async def list_events(db: AsyncSession, project_id: uuid.UUID) -> list[EventOut]:
    counts = dict(
        (
            await db.execute(
                select(EvidenceLink.event_id, func.count())
                .where(EvidenceLink.target_type == EvidenceTarget.EVENT)
                .group_by(EvidenceLink.event_id)
            )
        ).all()
    )
    events = (
        await db.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.project_id == project_id)
            .order_by(ActivityEvent.starts_on.nulls_last())
        )
    ).all()
    out = []
    for event in events:
        item = EventOut.model_validate(event)
        item.evidence_count = int(counts.get(event.id, 0))
        out.append(item)
    return out


async def suggest_events(db: AsyncSession, project_id: uuid.UUID) -> list[EventSuggestion]:
    """Group VERIFIED activity observations by (site, activity) into candidate events."""
    project = await get_project(db, project_id)
    taxonomy = await db.scalar(
        select(Taxonomy).where(
            Taxonomy.project_id == project.id, Taxonomy.version == project.active_taxonomy_version
        )
    )
    labels = {a["key"]: a["label"] for a in (taxonomy.activities if taxonomy else [])}
    sites = {
        s.id: s.name
        for s in (await db.scalars(select(Site).where(Site.project_id == project_id))).all()
    }
    rows = await db.execute(
        select(Observation.subject, Asset.site_id, Asset.id, Asset.capture_time)
        .join(Asset, Asset.id == Observation.asset_id)
        .where(
            Asset.project_id == project_id,
            Observation.ontology_type == OntologyType.ACTIVITY,
            Observation.status == ObservationStatus.VERIFIED,
            Observation.subject != "other",
        )
    )
    groups: dict[tuple[str, uuid.UUID | None], dict[str, object]] = defaultdict(
        lambda: {"assets": set(), "dates": [], "n": 0}
    )
    for subject, site_id, asset_id, captured in rows:
        g = groups[(subject, site_id)]
        g["assets"].add(asset_id)  # type: ignore[attr-defined]
        g["n"] = int(g["n"]) + 1  # type: ignore[call-overload]
        if captured:
            g["dates"].append(captured.date())  # type: ignore[attr-defined]
    out = []
    for (activity, site_id), g in groups.items():
        dates = sorted(g["dates"])  # type: ignore[type-var]
        label = labels.get(activity, activity.replace("_", " "))
        site_name = sites.get(site_id) if site_id else None
        out.append(
            EventSuggestion(
                activity=activity,
                activity_label=label,
                site_id=site_id,
                site_name=site_name,
                starts_on=dates[0] if dates else None,
                ends_on=dates[-1] if dates else None,
                asset_ids=sorted(g["assets"]),
                verified_observations=int(g["n"]),  # type: ignore[call-overload]
                suggested_title=f"{label}{f' at {site_name}' if site_name else ''}",
            )
        )
    return sorted(out, key=lambda s: (s.starts_on is None, s.starts_on))


async def project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    return await get_project(db, project_id)
