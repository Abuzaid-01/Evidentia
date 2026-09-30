"""Reports: drafts built from approved claims, a citation-checked narrative, immutable snapshots.

* A report includes only APPROVED claims. Metrics enter through the claims they are linked to.
* Narrative sentences (LLM-written or human-edited) must cite included claims/metrics, and every
  number must equal a cited metric value (domain/reports.py). Failing sentences never get stored.
* Publishing freezes a manifest (claims, evidence, observations with model versions, Cloudinary
  public_ids + transformations, approvers) and the HTML rendered purely from it. Both are hashed;
  `verify` re-renders the stored manifest and compares. The PDF is printed later by the worker.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import anyio
import structlog
from evidentia_ai.report_writer import ClaimBrief, MetricBrief, fallback_narrative, write_narrative
from evidentia_ai.text_llm import TextLLM
from evidentia_cloudinary.composite import signed_url
from evidentia_cloudinary.delivery import raw_download_url, rendition_url
from evidentia_cloudinary.transformations import for_resource
from evidentia_core import tasks
from evidentia_core.config import Settings
from evidentia_core.db.models import (
    ActivityEvent,
    AnalysisRun,
    Asset,
    BeforeAfterPair,
    Claim,
    ClaimMetric,
    EvidenceLink,
    Metric,
    Observation,
    Project,
    Report,
    ReportSnapshot,
    Site,
    User,
)
from evidentia_core.domain.before_after import alignment_grade
from evidentia_core.domain.enums import (
    AssetState,
    ClaimStatus,
    EvidenceRelation,
    EvidenceTarget,
    PdfStatus,
    ReportAudience,
    ReportStatus,
    ResourceType,
)
from evidentia_core.domain.reports import (
    CLAIM_TYPE_ORDER,
    MANIFEST_VERSION,
    NARRATIVE_SECTIONS,
    Citation,
    CitationContext,
    check_narrative,
    decimal_text,
    derive_limitations,
    has_content,
    jsonable,
    manifest_hash,
    normalize_narrative,
    periods_overlap,
    sentence_problems,
    sha256_hex,
    split_sentences,
)
from evidentia_reporting import RENDERER_VERSION, render_html, renderer_version
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.errors import Conflict, NotFound, ServiceUnavailable, Unprocessable
from evidentia_api.schemas.reports import (
    DownloadLink,
    NarrativeIn,
    RenderedReport,
    ReportClaim,
    ReportCreate,
    ReportDetail,
    ReportOut,
    ReportUpdate,
    SentenceProblemOut,
    SnapshotOut,
    SnapshotVerification,
)
from evidentia_api.services import audit
from evidentia_api.services.projects import get_project, get_site

log = structlog.get_logger("evidentia.reports")

_HAS_MEDIA = {AssetState.READY, AssetState.REVIEW_REQUIRED, AssetState.INDEXED}


# --- loading ----------------------------------------------------------------------------------------


async def get_report(db: AsyncSession, report_id: uuid.UUID, *, lock: bool = False) -> Report:
    query = select(Report).where(Report.id == report_id)
    report = await db.scalar(query.with_for_update() if lock else query)
    if report is None:
        raise NotFound("Report not found")
    return report


async def get_snapshot(db: AsyncSession, report_id: uuid.UUID, version: int) -> ReportSnapshot:
    snapshot = await db.scalar(
        select(ReportSnapshot).where(
            ReportSnapshot.report_id == report_id, ReportSnapshot.version == version
        )
    )
    if snapshot is None:
        raise NotFound(f"Report version {version} not found")
    return snapshot


def _order_key(claim: Claim) -> tuple[int, date, datetime, str]:
    return (
        CLAIM_TYPE_ORDER[claim.claim_type],
        claim.period_start or date.min,
        claim.created_at,
        str(claim.id),
    )


async def _claims_by_ids(db: AsyncSession, ids: list[Any]) -> list[Claim]:
    if not ids:
        return []
    rows = await db.scalars(select(Claim).where(Claim.id.in_([uuid.UUID(str(i)) for i in ids])))
    return sorted(rows.all(), key=_order_key)


async def _approved_in_scope(
    db: AsyncSession,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None,
    start: date | None,
    end: date | None,
) -> list[Claim]:
    rows = await db.scalars(
        select(Claim).where(Claim.project_id == project_id, Claim.status == ClaimStatus.APPROVED)
    )
    return sorted(
        (
            c
            for c in rows.all()
            if (site_id is None or c.site_id in (site_id, None))
            and periods_overlap(start, end, c.period_start, c.period_end)
        ),
        key=_order_key,
    )


async def _checked_claim_ids(
    db: AsyncSession, project_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[str]:
    unique = list(dict.fromkeys(ids))
    claims = await _claims_by_ids(db, unique)
    if len(claims) != len(unique) or any(c.project_id != project_id for c in claims):
        raise Unprocessable("Some claims were not found in this project")
    not_approved = [str(c.id) for c in claims if c.status != ClaimStatus.APPROVED]
    if not_approved:
        raise Unprocessable(
            "Only approved claims can go into a report", details={"claim_ids": not_approved}
        )
    return [str(c.id) for c in claims]


async def _metrics_for(
    db: AsyncSession, claim_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Metric]]:
    out: dict[uuid.UUID, list[Metric]] = {cid: [] for cid in claim_ids}
    if not claim_ids:
        return out
    rows = await db.execute(
        select(ClaimMetric.claim_id, Metric)
        .join(Metric, Metric.id == ClaimMetric.metric_id)
        .where(ClaimMetric.claim_id.in_(claim_ids))
        .order_by(Metric.name, Metric.id)
    )
    for claim_id, metric in rows.all():
        out[claim_id].append(metric)
    return out


async def _scope(
    db: AsyncSession, report: Report
) -> tuple[list[Claim], dict[uuid.UUID, list[Metric]], CitationContext]:
    """Included claims that are still approved, their metrics, and what may be cited."""
    claims = [
        c for c in await _claims_by_ids(db, report.claim_ids) if c.status == ClaimStatus.APPROVED
    ]
    metrics = await _metrics_for(db, [c.id for c in claims])
    ctx = CitationContext(
        claim_metrics={str(c.id): frozenset(str(m.id) for m in metrics[c.id]) for c in claims},
        metric_values={str(m.id): Decimal(m.value) for ms in metrics.values() for m in ms},
    )
    return claims, metrics, ctx


def _ordered_metrics(claims: list[Claim], metrics: dict[uuid.UUID, list[Metric]]) -> list[Metric]:
    seen: dict[uuid.UUID, Metric] = {}
    for claim in claims:
        for metric in metrics[claim.id]:
            seen.setdefault(metric.id, metric)
    return list(seen.values())


async def _user_names(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    users = (await db.scalars(select(User).where(User.id.in_(wanted)))).all()
    return {u.id: u.display_name or u.email or "unknown" for u in users}


# --- drafts --------------------------------------------------------------------------------------------


async def create_report(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    body: ReportCreate,
    rid: str | None,
) -> Report:
    await get_project(db, project_id)
    if body.site_id and (await get_site(db, body.site_id)).project_id != project_id:
        raise Unprocessable("Site does not belong to this project")
    if body.claim_ids is None:
        claim_ids = [
            str(c.id)
            for c in await _approved_in_scope(
                db, project_id, body.site_id, body.period_start, body.period_end
            )
        ]
    else:
        claim_ids = await _checked_claim_ids(db, project_id, body.claim_ids)
    report = Report(
        organization_id=principal.org_id,
        project_id=project_id,
        created_by_id=principal.user_id,
        claim_ids=claim_ids,
        **body.model_dump(exclude={"claim_ids"}),
    )
    db.add(report)
    await db.flush()
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="report.created",
        target_type="report",
        target_id=report.id,
        data={"title": report.title, "claims": len(claim_ids)},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(report)
    return report


async def update_report(
    db: AsyncSession,
    principal: Principal,
    report_id: uuid.UUID,
    body: ReportUpdate,
    rid: str | None,
) -> Report:
    report = await get_report(db, report_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("site_id") and (
        (await get_site(db, changes["site_id"])).project_id != report.project_id
    ):
        raise Unprocessable("Site does not belong to this project")
    if "claim_ids" in changes:
        changes["claim_ids"] = await _checked_claim_ids(
            db, report.project_id, changes["claim_ids"] or []
        )
    for field, value in changes.items():
        setattr(report, field, value)
    start, end = report.period_start, report.period_end
    if start and end and end < start:
        raise Unprocessable("period_end must be on or after period_start")
    audit.record(
        db,
        org_id=report.organization_id,
        principal=principal,
        action="report.updated",
        target_type="report",
        target_id=report.id,
        data={k: str(v) if not isinstance(v, list) else len(v) for k, v in changes.items()},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(report)
    return report


# --- narrative -------------------------------------------------------------------------------------------

# "[C1]" / "[C1, M2]" markers a model may leave inside the text despite instructions
_INLINE_REFS = re.compile(r"\s*\[((?:[CM]\d+)(?:\s*,\s*[CM]\d+)*)\]")


def _resolve_refs(
    sections: dict[str, list[dict[str, Any]]],
    refmap: dict[str, dict[str, str]],
    ctx: CitationContext,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Model output (refs) -> stored narrative (ids). Each sentence is checked; failures are
    returned separately and never stored."""
    narrative: dict[str, list[dict[str, Any]]] = {s: [] for s in NARRATIVE_SECTIONS}
    rejected: list[dict[str, Any]] = []
    for section in NARRATIVE_SECTIONS:
        for item in sections.get(section) or []:
            refs = [str(r).strip() for r in item.get("cites") or []]
            text = str(item.get("text", ""))
            for group in _INLINE_REFS.findall(text):
                refs += [r.strip() for r in group.split(",")]
            text = _INLINE_REFS.sub("", text)
            unknown = sorted({r for r in refs if r not in refmap})
            cites = list({refmap[r]["id"]: refmap[r] for r in refs if r in refmap}.values())
            for sentence in split_sentences(text):
                problems = [f"Unknown reference {r}" for r in unknown]
                problems += sentence_problems(sentence, [Citation.parse(c) for c in cites], ctx)
                if problems:
                    rejected.append({"section": section, "text": sentence, "problems": problems})
                else:
                    narrative[section].append({"text": sentence, "cites": cites})
    return narrative, rejected


def _month(value: datetime | date | None) -> str | None:
    return value.strftime("%B %Y") if value else None


def _period_text(start: date | None, end: date | None) -> str | None:
    if not (start or end):
        return None
    return f"{_month(start) or 'start'} to {_month(end) or 'now'}"


async def _briefs(
    db: AsyncSession, claims: list[Claim], metrics: dict[uuid.UUID, list[Metric]]
) -> tuple[list[ClaimBrief], list[MetricBrief], dict[str, dict[str, str]]]:
    ordered_metrics = _ordered_metrics(claims, metrics)
    metric_ref = {m.id: f"M{i}" for i, m in enumerate(ordered_metrics, 1)}
    sites = {
        s.id: s.name
        for s in (
            await db.scalars(
                select(Site).where(Site.id.in_({c.site_id for c in claims if c.site_id}))
            )
        ).all()
    }
    rows = await db.execute(
        select(EvidenceLink.claim_id, Observation, Asset, BeforeAfterPair)
        .join(Asset, Asset.id == EvidenceLink.asset_id)
        .outerjoin(Observation, Observation.id == EvidenceLink.observation_id)
        .outerjoin(BeforeAfterPair, BeforeAfterPair.id == EvidenceLink.pair_id)
        .where(
            EvidenceLink.claim_id.in_([c.id for c in claims]),
            EvidenceLink.relation == EvidenceRelation.SUPPORTS,
        )
        .order_by(EvidenceLink.created_at)
    )
    evidence: dict[uuid.UUID, list[str]] = {c.id: [] for c in claims}
    for claim_id, obs, asset, pair in rows.all():
        if pair is not None:
            what = f"confirmed before/after photo comparison: {pair.change_summary or 'visible change'}"
        elif obs:
            what = f"{obs.subject.replace('_', ' ')} {obs.predicate} ({obs.status.value})"
        else:
            what = asset.caption or "reviewed media"
        when = _month(asset.capture_time)
        evidence[claim_id].append(f"{what}{f', captured {when}' if when else ''}")
    claim_briefs = [
        ClaimBrief(
            ref=f"C{i}",
            claim_type=c.claim_type.value,
            statement=c.statement,
            site=sites.get(c.site_id) if c.site_id else None,
            period=_period_text(c.period_start, c.period_end),
            metric_refs=[metric_ref[m.id] for m in metrics[c.id]],
            evidence=evidence[c.id][:6],
        )
        for i, c in enumerate(claims, 1)
    ]
    metric_briefs = [
        MetricBrief(
            ref=metric_ref[m.id],
            name=m.name,
            value=decimal_text(Decimal(m.value)),
            unit=m.unit,
            source=f"{m.source_type.value}: {m.source_reference}",
        )
        for m in ordered_metrics
    ]
    refmap = {
        b.ref: {"type": "claim", "id": str(c.id)} for b, c in zip(claim_briefs, claims, strict=True)
    }
    refmap |= {metric_ref[m.id]: {"type": "metric", "id": str(m.id)} for m in ordered_metrics}
    return claim_briefs, metric_briefs, refmap


async def generate_narrative(
    db: AsyncSession,
    principal: Principal,
    report_id: uuid.UUID,
    llms: list[TextLLM],
    rid: str | None,
) -> Report:
    report = await get_report(db, report_id, lock=True)
    claims, metrics, ctx = await _scope(db, report)
    if not claims:
        raise Unprocessable("Add at least one approved claim before generating the narrative")
    project = await db.get(Project, report.project_id)
    claim_briefs, metric_briefs, refmap = await _briefs(db, claims, metrics)
    draft = await anyio.to_thread.run_sync(
        lambda: write_narrative(
            project=project.name if project else "",
            period=_period_text(report.period_start, report.period_end),
            audience=report.audience.value,
            claims=claim_briefs,
            metrics=metric_briefs,
            llms=llms,
        )
    )
    narrative, rejected = _resolve_refs(draft.sections, refmap, ctx)
    meta = dict(draft.meta)
    if not has_content(narrative):
        narrative, fallback_rejected = _resolve_refs(fallback_narrative(claim_briefs), refmap, ctx)
        rejected += fallback_rejected
        if meta.get("mode") == "llm":
            meta |= {"mode": "fallback", "reason": "no model sentence passed the citation checks"}
    report.narrative = narrative
    report.narrative_meta = {
        **meta,
        "rejected": rejected,
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by_id": str(principal.user_id),
        "edited_by": None,
    }
    audit.record(
        db,
        org_id=report.organization_id,
        principal=principal,
        action="report.narrative_generated",
        target_type="report",
        target_id=report.id,
        data={
            "mode": meta.get("mode"),
            "model": meta.get("model"),
            "sentences": sum(len(v) for v in narrative.values()),
            "rejected": len(rejected),
        },
        request_id=rid,
    )
    await db.commit()
    await db.refresh(report)
    return report


async def set_narrative(
    db: AsyncSession, principal: Principal, report_id: uuid.UUID, body: NarrativeIn, rid: str | None
) -> Report:
    report = await get_report(db, report_id, lock=True)
    _, _, ctx = await _scope(db, report)
    narrative = normalize_narrative(body.model_dump(mode="json"))
    problems = check_narrative(narrative, ctx)
    if problems:
        raise Unprocessable(
            "Some sentences break the citation rules", details=[p.as_dict() for p in problems]
        )
    names = await _user_names(db, {principal.user_id})
    report.narrative = narrative
    report.narrative_meta = {
        **(report.narrative_meta or {"mode": "manual"}),
        "edited_by": names.get(principal.user_id, "unknown"),
        "edited_by_id": str(principal.user_id),
        "edited_at": datetime.now(UTC).isoformat(),
    }
    audit.record(
        db,
        org_id=report.organization_id,
        principal=principal,
        action="report.narrative_edited",
        target_type="report",
        target_id=report.id,
        data={"sentences": sum(len(v) for v in narrative.values())},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(report)
    return report


# --- manifest -------------------------------------------------------------------------------------------


def _figure(
    asset: Asset, audience: ReportAudience, settings: Settings, *, cloudinary_ready: bool
) -> dict[str, Any] | None:
    """Which rendition represents this asset in the report. External reports only ever use the
    face-redacted rendition, and skip video until redacted video exists (Phase 8)."""
    video = asset.resource_type == ResourceType.VIDEO
    if audience == ReportAudience.EXTERNAL and video:
        return None
    variant = "public_redacted" if audience == ReportAudience.EXTERNAL else "thumb"
    nt = for_resource(asset.resource_type.value)[variant]
    named = settings.cloudinary_use_named_transformations
    url = None
    if cloudinary_ready and asset.state in _HAS_MEDIA:
        url = rendition_url(
            asset.public_id, asset.resource_type.value, variant, use_named=named
        ).url
    return {
        "variant": variant,
        "named_transformation": nt.name if named else None,
        "transformation": nt.definition,
        "url": url,
    }


def _alignment_entry(pair: BeforeAfterPair) -> dict[str, Any]:
    a = pair.alignment or {}
    return {
        "grade": alignment_grade(pair.alignment),
        "method": a.get("method"),
        "inliers": a.get("inliers"),
        "inlier_ratio": a.get("inlier_ratio"),
        "overlap": a.get("overlap"),
    }


def _change_entry(pair: BeforeAfterPair) -> dict[str, Any]:
    c = pair.changes or {}
    return {
        "summary": pair.change_summary,
        "method": c.get("method"),
        "changed_share": c.get("changed_share"),
        "green_cover_before": c.get("green_cover_before"),
        "green_cover_after": c.get("green_cover_after"),
        "ssim_mean": c.get("ssim_mean"),
    }


def _composite_figure(
    pair: BeforeAfterPair, before: Asset, audience: ReportAudience, *, cloudinary_ready: bool
) -> dict[str, Any] | None:
    """External reports only ever use the face-pixelated composite."""
    external = audience == ReportAudience.EXTERNAL
    raw = pair.public_composite_transformation if external else pair.composite_transformation
    if not raw:
        return None
    variant = "before_after_public" if external else "before_after"
    return {
        "variant": variant,
        "transformation": raw,
        "url": signed_url(before.public_id, raw, variant=variant).url if cloudinary_ready else None,
    }


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def _asset_url(web: str, asset_id: uuid.UUID, links: list[Any]) -> str:
    """Open the asset, and seek when the evidence link carries a video span."""
    base = f"{web}/assets/{asset_id}"
    for link in links:
        if link.asset_id != asset_id or not link.span:
            continue
        start = link.span.get("start_ms")
        if isinstance(start, int):
            return f"{base}?t={start // 1000}"
    return base


async def build_manifest(
    db: AsyncSession,
    report: Report,
    settings: Settings,
    *,
    cloudinary_ready: bool,
    published: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[SentenceProblemOut]]:
    """Everything the rendered report shows, and where each piece came from. Returns the manifest
    and the narrative problems (failing sentences are left out of the manifest)."""
    claims, metrics, ctx = await _scope(db, report)
    project = await get_project(db, report.project_id)
    sites = {
        s.id: s for s in (await db.scalars(select(Site).where(Site.project_id == project.id))).all()
    }
    internal = report.audience == ReportAudience.INTERNAL
    web = settings.web_base_url.rstrip("/")

    ordered_metrics = _ordered_metrics(claims, metrics)
    claim_ref = {c.id: f"C{i}" for i, c in enumerate(claims, 1)}
    metric_ref = {m.id: f"M{i}" for i, m in enumerate(ordered_metrics, 1)}

    links = (
        await db.scalars(
            select(EvidenceLink)
            .where(EvidenceLink.claim_id.in_(list(claim_ref)))
            .order_by(EvidenceLink.created_at, EvidenceLink.id)
        )
    ).all()
    position = {cid: i for i, cid in enumerate(claim_ref)}
    links = sorted(links, key=lambda lk: position[lk.claim_id])  # type: ignore[index]  # stable
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
    runs = {
        r.id: r
        for r in (
            await db.scalars(
                select(AnalysisRun).where(
                    AnalysisRun.id.in_(
                        [o.analysis_run_id for o in observations.values() if o.analysis_run_id]
                    )
                )
            )
        ).all()
    }
    pairs = {
        p.id: p
        for p in (
            await db.scalars(
                select(BeforeAfterPair).where(
                    BeforeAfterPair.id.in_([lk.pair_id for lk in links if lk.pair_id])
                )
            )
        ).all()
    }
    assets = {
        a.id: a
        for a in (
            await db.scalars(
                select(Asset).where(
                    Asset.id.in_(
                        [lk.asset_id for lk in links] + [p.before_asset_id for p in pairs.values()]
                    )
                )
            )
        ).all()
    }
    asset_ref: dict[uuid.UUID, str] = {}
    pair_ref: dict[uuid.UUID, str] = {}
    for link in links:
        if link.pair_id and link.pair_id in pairs:  # number the before photo first
            asset_ref.setdefault(pairs[link.pair_id].before_asset_id, f"A{len(asset_ref) + 1}")
            pair_ref.setdefault(link.pair_id, f"B{len(pair_ref) + 1}")
        asset_ref.setdefault(link.asset_id, f"A{len(asset_ref) + 1}")
    evidence_ref = {lk.id: f"E{i}" for i, lk in enumerate(links, 1)}
    names = await _user_names(
        db,
        {c.created_by_id for c in claims}
        | {c.decided_by_id for c in claims}
        | {o.reviewer_id for o in observations.values()}
        | {p.decided_by_id for p in pairs.values()},
    )

    def person(user_id: uuid.UUID | None) -> dict[str, Any]:
        if user_id is None:
            return {"id": None, "name": "unknown"}
        return {"id": str(user_id), "name": names.get(user_id, "unknown")}

    def site_name(site_id: uuid.UUID | None) -> str | None:
        return sites[site_id].name if site_id and site_id in sites else None

    claim_entries = []
    for claim in claims:
        v = claim.validation or {}
        claim_entries.append(
            {
                "ref": claim_ref[claim.id],
                "id": str(claim.id),
                "statement": claim.statement,
                "claim_type": claim.claim_type.value,
                "support_level": claim.support_level.value,
                "site": site_name(claim.site_id),
                "period_start": _iso(claim.period_start),
                "period_end": _iso(claim.period_end),
                "author": person(claim.created_by_id),
                "approved_by": person(claim.decided_by_id),
                "approved_at": _iso(claim.decided_at),
                "decision_note": claim.decision_note,
                "validation": {
                    "verdict": claim.validation_verdict.value,
                    "provider": v.get("provider"),
                    "model": v.get("model"),
                    "version": v.get("version"),
                    "reasoning": v.get("reasoning"),
                }
                if claim.validation_verdict
                else None,
                "rule_check": claim.rule_check,
                "evidence_refs": [evidence_ref[lk.id] for lk in links if lk.claim_id == claim.id],
                "metric_refs": [metric_ref[m.id] for m in metrics[claim.id]],
                "app_url": f"{web}/claims/{claim.id}" if internal else None,
            }
        )

    metric_entries = [
        {
            "ref": metric_ref[m.id],
            "id": str(m.id),
            "name": m.name,
            "value": decimal_text(Decimal(m.value)),
            "unit": m.unit,
            "method": m.method,
            "source_type": m.source_type.value,
            "source_reference": m.source_reference,
            "period_start": _iso(m.period_start),
            "period_end": _iso(m.period_end),
            "site": site_name(m.site_id),
        }
        for m in ordered_metrics
    ]

    evidence_entries = []
    for link in links:
        obs = observations.get(link.observation_id) if link.observation_id else None
        run = runs.get(obs.analysis_run_id) if obs and obs.analysis_run_id else None
        evidence_entries.append(
            {
                "ref": evidence_ref[link.id],
                "link_id": str(link.id),
                "claim_ref": claim_ref[link.claim_id],  # type: ignore[index]
                "asset_ref": asset_ref[link.asset_id],
                "relation": link.relation.value,
                "note": link.note,
                "span": link.span,
                "pair_ref": pair_ref.get(link.pair_id) if link.pair_id else None,
                "observation": {
                    "id": str(obs.id),
                    "ontology_type": obs.ontology_type.value,
                    "subject": obs.subject,
                    "predicate": obs.predicate,
                    "status": obs.status.value,
                    "confidence": obs.confidence,
                    "source_kind": obs.source_kind.value,
                    "source_provider": obs.source_provider,
                    "reviewer": person(obs.reviewer_id) if obs.reviewer_id else None,
                    "reviewed_at": _iso(obs.reviewed_at),
                    "run": {
                        "provider": run.provider,
                        "model": run.model,
                        "model_version": run.model_version,
                        "prompt_version": run.prompt_version,
                        "schema_version": run.schema_version,
                        "taxonomy_version": run.taxonomy_version,
                    }
                    if run
                    else None,
                }
                if obs
                else None,
            }
        )

    asset_entries = []
    for asset_id, ref in asset_ref.items():
        a = assets[asset_id]
        asset_entries.append(
            {
                "ref": ref,
                "id": str(a.id),
                "public_id": a.public_id,
                "cloudinary_asset_id": a.cloudinary_asset_id,
                "cloudinary_version": a.cloudinary_version,
                "resource_type": a.resource_type.value,
                "format": a.format,
                "sha256": a.sha256,
                "original_filename": a.original_filename,
                "caption": a.caption,
                "capture_time": _iso(a.capture_time),
                "capture_time_source": a.capture_time_source.value,
                "location_source": a.location_source.value,
                "site": site_name(a.site_id),
                "reviewed_at": _iso(a.reviewed_at),
                "figure": _figure(a, report.audience, settings, cloudinary_ready=cloudinary_ready),
                "app_url": _asset_url(web, a.id, links) if internal else None,
            }
        )

    comparison_entries = []
    for pid, ref in pair_ref.items():
        pair = pairs[pid]
        pair_links = [lk for lk in links if lk.pair_id == pid]
        comparison_entries.append(
            {
                "ref": ref,
                "id": str(pair.id),
                "before_asset_ref": asset_ref[pair.before_asset_id],
                "after_asset_ref": asset_ref[pair.after_asset_id],
                "claim_refs": list(dict.fromkeys(claim_ref[lk.claim_id] for lk in pair_links)),  # type: ignore[index]
                "evidence_refs": [evidence_ref[lk.id] for lk in pair_links],
                "days_apart": pair.days_apart,
                "confirmed_by": person(pair.decided_by_id),
                "confirmed_at": _iso(pair.decided_at),
                "decision_note": pair.decision_note,
                "analysis_version": pair.analysis_version,
                "alignment": _alignment_entry(pair),
                "change": _change_entry(pair),
                "limitations": list(pair.limitations or []),
                "figure": _composite_figure(
                    pair,
                    assets[pair.before_asset_id],
                    report.audience,
                    cloudinary_ready=cloudinary_ready,
                ),
            }
        )

    # timeline: activity events in scope + dated claims
    events = (
        await db.scalars(select(ActivityEvent).where(ActivityEvent.project_id == project.id))
    ).all()
    counts = dict(
        (
            await db.execute(
                select(EvidenceLink.event_id, func.count())
                .where(EvidenceLink.target_type == EvidenceTarget.EVENT)
                .group_by(EvidenceLink.event_id)
            )
        ).all()
    )
    timeline = [
        {
            "kind": "event",
            "title": e.title,
            "starts_on": _iso(e.starts_on),
            "ends_on": _iso(e.ends_on),
            "site": site_name(e.site_id),
            "ref": None,
            "evidence_count": int(counts.get(e.id, 0)),
            "time_source": None,
        }
        for e in events
        if (report.site_id is None or e.site_id in (report.site_id, None))
        and periods_overlap(report.period_start, report.period_end, e.starts_on, e.ends_on)
    ]
    timeline += [
        {
            "kind": "claim",
            "title": c.statement,
            "starts_on": _iso(c.period_start),
            "ends_on": _iso(c.period_end),
            "site": site_name(c.site_id),
            "ref": claim_ref[c.id],
            "evidence_count": 0,
            "time_source": None,
        }
        for c in claims
        if c.period_start or c.period_end
    ]
    # when each photo was taken (or uploaded, when it carries no camera time) ...
    timeline += [
        {
            "kind": "photo",
            "title": a["caption"] or a["original_filename"] or "Field photo",
            "starts_on": a["capture_time"],
            "ends_on": None,
            "site": a["site"],
            "ref": a["ref"],
            "evidence_count": 0,
            "time_source": a["capture_time_source"],
        }
        for a in asset_entries
        if a["capture_time"]
    ]
    # ... and when a second person approved each claim
    timeline += [
        {
            "kind": "approval",
            "title": c["statement"],
            "starts_on": c["approved_at"],
            "ends_on": None,
            "site": c["site"],
            "ref": c["ref"],
            "evidence_count": 0,
            "time_source": None,
        }
        for c in claim_entries
        if c["approved_at"]
    ]
    kind_order = {"event": 0, "claim": 1, "photo": 2, "approval": 3}
    timeline.sort(
        key=lambda t: (t["starts_on"] or t["ends_on"] or "9999", kind_order[t["kind"]], t["title"])
    )

    # narrative: only sentences that pass the checks; cites become refs
    ref_of = {str(c.id): claim_ref[c.id] for c in claims} | {
        str(m.id): metric_ref[m.id] for m in ordered_metrics
    }
    stored = report.narrative or {}
    problems = check_narrative(stored, ctx)
    failing = {(p.section, p.index) for p in problems}
    narrative: dict[str, Any] = {
        section: [
            {"text": item["text"], "cites": [ref_of[c["id"]] for c in item.get("cites") or []]}
            for index, item in enumerate(stored.get(section) or [])
            if (section, index) not in failing
        ]
        for section in NARRATIVE_SECTIONS
    }
    meta = report.narrative_meta or {}
    narrative["generator"] = {
        "mode": meta.get("mode", "manual"),
        "provider": meta.get("provider"),
        "model": meta.get("model"),
        "version": meta.get("version"),
        "edited_by": meta.get("edited_by"),
    }

    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "report": {
            "id": str(report.id),
            "title": report.title,
            "audience": report.audience.value,
            "period_start": _iso(report.period_start),
            "period_end": _iso(report.period_end),
            "project": {"id": str(project.id), "name": project.name},
            "site": {
                "id": str(report.site_id),
                "name": sites[report.site_id].name,
                "code": sites[report.site_id].code,
            }
            if report.site_id and report.site_id in sites
            else None,
        },
        "published": published,
        "narrative": narrative,
        "claims": claim_entries,
        "metrics": metric_entries,
        "evidence": evidence_entries,
        "assets": asset_entries,
        "comparisons": comparison_entries,
        "timeline": timeline,
        "production": {
            "analysis_models": sorted(
                {
                    f"{e['observation']['run']['provider']}/{e['observation']['run']['model']}"
                    for e in evidence_entries
                    if e["observation"] and e["observation"].get("run")
                }
            ),
            "validation_models": sorted(
                {
                    f"{c['validation']['provider']}/{c['validation']['model']}"
                    for c in claim_entries
                    if c["validation"] and c["validation"].get("model")
                }
            ),
        },
    }
    manifest["limitations"] = [
        {"text": item["text"], "cites": [ref_of[c["id"]] for c in item["cites"]]}
        for item in derive_limitations(manifest)
    ]
    return jsonable(manifest), [SentenceProblemOut(**p.as_dict()) for p in problems]


# --- views ---------------------------------------------------------------------------------------------------


def _claim_out(claim: Claim) -> ReportClaim:
    return ReportClaim.model_validate(claim)


async def _snapshot_outs(db: AsyncSession, snapshots: list[ReportSnapshot]) -> list[SnapshotOut]:
    ids = {c["id"] for s in snapshots for c in s.manifest.get("claims") or []}
    retracted = set()
    if ids:
        retracted = {
            str(i)
            for i in (
                await db.scalars(
                    select(Claim.id).where(
                        Claim.id.in_([uuid.UUID(i) for i in ids]),
                        Claim.status != ClaimStatus.APPROVED,
                    )
                )
            ).all()
        }
    out = []
    for snap in snapshots:
        item = SnapshotOut.model_validate(snap)
        item.retracted_claim_ids = [
            uuid.UUID(c["id"]) for c in snap.manifest.get("claims") or [] if c["id"] in retracted
        ]
        out.append(item)
    return out


async def list_snapshots(db: AsyncSession, report_id: uuid.UUID) -> list[SnapshotOut]:
    rows = (
        await db.scalars(
            select(ReportSnapshot)
            .where(ReportSnapshot.report_id == report_id)
            .order_by(ReportSnapshot.version.desc())
        )
    ).all()
    return await _snapshot_outs(db, list(rows))


async def report_detail(db: AsyncSession, report: Report) -> ReportDetail:
    included = await _claims_by_ids(db, report.claim_ids)
    _, _, ctx = await _scope(db, report)
    problems = check_narrative(report.narrative or {}, ctx)
    included_ids = {c.id for c in included}
    candidates = [
        c
        for c in await _approved_in_scope(db, report.project_id, None, None, None)
        if c.id not in included_ids
    ]
    warnings = []
    stale = [c for c in included if c.status != ClaimStatus.APPROVED]
    if stale:
        warnings.append(
            f"{len(stale)} included claim(s) are no longer approved; remove them before publishing"
        )
    if not included:
        warnings.append("No claims are included yet")
    if not has_content(report.narrative):
        warnings.append("Generate or write the narrative before publishing")
    if problems:
        warnings.append(f"{len(problems)} narrative sentence(s) fail the citation checks")
    return ReportDetail(
        **ReportOut.model_validate(report).model_dump(),
        narrative=report.narrative,
        narrative_meta=report.narrative_meta,
        narrative_problems=[SentenceProblemOut(**p.as_dict()) for p in problems],
        claims=[_claim_out(c) for c in included],
        candidate_claims=[_claim_out(c) for c in candidates],
        snapshots=await list_snapshots(db, report.id),
        warnings=warnings,
    )


async def preview(
    db: AsyncSession, report: Report, settings: Settings, *, cloudinary_ready: bool
) -> RenderedReport:
    manifest, problems = await build_manifest(
        db, report, settings, cloudinary_ready=cloudinary_ready
    )
    return RenderedReport(
        html=render_html(manifest), manifest_sha256=manifest_hash(manifest), problems=problems
    )


# --- publishing ----------------------------------------------------------------------------------------------


async def publish(
    db: AsyncSession,
    principal: Principal,
    report_id: uuid.UUID,
    settings: Settings,
    *,
    cloudinary_ready: bool,
    rid: str | None,
) -> SnapshotOut:
    report = await get_report(db, report_id, lock=True)
    included = await _claims_by_ids(db, report.claim_ids)
    if not included:
        raise Unprocessable("A report needs at least one approved claim")
    stale = [str(c.id) for c in included if c.status != ClaimStatus.APPROVED]
    if stale:
        raise Unprocessable(
            "Some included claims are no longer approved; remove them first",
            details={"claim_ids": stale},
        )
    if not has_content(report.narrative):
        raise Unprocessable("Generate or write the narrative before publishing")
    _, _, ctx = await _scope(db, report)
    problems = check_narrative(report.narrative or {}, ctx)
    if problems:
        raise Unprocessable(
            "Some sentences break the citation rules; regenerate or edit the narrative",
            details=[p.as_dict() for p in problems],
        )

    version = report.latest_version + 1
    now = datetime.now(UTC)
    names = await _user_names(db, {principal.user_id})
    manifest, _ = await build_manifest(
        db,
        report,
        settings,
        cloudinary_ready=cloudinary_ready,
        published={
            "version": version,
            "published_at": now.isoformat(),
            "published_by": {
                "id": str(principal.user_id),
                "name": names.get(principal.user_id, "unknown"),
            },
        },
    )
    html = render_html(manifest)
    snapshot = ReportSnapshot(
        organization_id=report.organization_id,
        report_id=report.id,
        version=version,
        manifest=manifest,
        manifest_sha256=manifest_hash(manifest),
        html_sha256=sha256_hex(html),
        renderer_version=renderer_version(manifest),
        published_by_id=principal.user_id,
        published_at=now,
        pdf_status=PdfStatus.PENDING if cloudinary_ready else PdfStatus.SKIPPED,
        pdf_error=None if cloudinary_ready else "Cloudinary is not configured (CLOUDINARY_URL)",
    )
    db.add(snapshot)
    report.status = ReportStatus.PUBLISHED
    report.latest_version = version
    report.published_at = now
    await db.flush()
    audit.record(
        db,
        org_id=report.organization_id,
        principal=principal,
        action="report.published",
        target_type="report",
        target_id=report.id,
        data={
            "version": version,
            "snapshot_id": str(snapshot.id),
            "manifest_sha256": snapshot.manifest_sha256,
            "claims": len(manifest["claims"]),
            "assets": len(manifest["assets"]),
        },
        request_id=rid,
    )
    await db.commit()
    await db.refresh(snapshot)
    if cloudinary_ready:
        _enqueue_pdf(snapshot.id)
    return (await _snapshot_outs(db, [snapshot]))[0]


def _enqueue_pdf(snapshot_id: uuid.UUID) -> None:
    try:
        tasks.enqueue(tasks.RENDER_REPORT_PDF, str(snapshot_id))
    except Exception as exc:  # the snapshot is safe; the PDF can be re-requested
        log.warning("report_pdf_enqueue_failed", snapshot_id=str(snapshot_id), error=str(exc))


async def public_report_view(
    db: AsyncSession, snapshot: ReportSnapshot, settings: Settings, *, cloudinary_ready: bool
) -> dict[str, Any]:
    """What a public share link shows: never the internal record itself.

    An externally published snapshot is served exactly as published (verifiable, with its PDF). An
    internal one is turned into a privacy-redacted copy first: every image becomes Cloudinary's
    face-pixelated rendition (videos are left out), and links into the app are removed.
    """
    manifest = snapshot.manifest
    official = manifest["report"]["audience"] == ReportAudience.EXTERNAL.value
    public = manifest
    if not official:
        public = jsonable(manifest)  # deep copy
        public["report"]["audience"] = ReportAudience.EXTERNAL.value
        for claim in public.get("claims") or []:
            claim["app_url"] = None
        asset_ids = [uuid.UUID(a["id"]) for a in public.get("assets") or []]
        rows = {
            a.id: a for a in (await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))).all()
        }
        for entry in public.get("assets") or []:
            row = rows.get(uuid.UUID(entry["id"]))
            entry["app_url"] = None
            entry["figure"] = (
                _figure(row, ReportAudience.EXTERNAL, settings, cloudinary_ready=cloudinary_ready)
                if row
                else None
            )
        for comparison in public.get("comparisons") or []:
            pair = await db.get(BeforeAfterPair, uuid.UUID(comparison["id"]))
            before = await db.get(Asset, pair.before_asset_id) if pair else None
            comparison["figure"] = (
                _composite_figure(
                    pair, before, ReportAudience.EXTERNAL, cloudinary_ready=cloudinary_ready
                )
                if pair and before
                else None
            )
    pdf_url = None
    if official and snapshot.pdf_status == PdfStatus.READY and snapshot.pdf_public_id:
        pdf_url = raw_download_url(snapshot.pdf_public_id, ttl_seconds=600).url
    return {
        "title": manifest["report"]["title"],
        "version": snapshot.version,
        "published_at": snapshot.published_at.isoformat(),
        "html": render_html(public),
        "redacted_copy": not official,
        "fingerprint": manifest_hash(public),
        "published_fingerprint": snapshot.manifest_sha256,
        "pdf_url": pdf_url,
    }


def verify_snapshot(snapshot: ReportSnapshot) -> SnapshotVerification:
    recomputed_manifest = manifest_hash(snapshot.manifest)
    recomputed_html = sha256_hex(render_html(snapshot.manifest))
    return SnapshotVerification(
        version=snapshot.version,
        manifest_sha256=snapshot.manifest_sha256,
        recomputed_manifest_sha256=recomputed_manifest,
        html_sha256=snapshot.html_sha256,
        recomputed_html_sha256=recomputed_html,
        renderer_version=snapshot.renderer_version,
        current_renderer_version=RENDERER_VERSION,
        identical=recomputed_manifest == snapshot.manifest_sha256
        and recomputed_html == snapshot.html_sha256,
    )


async def pdf_link(
    db: AsyncSession, principal: Principal, snapshot: ReportSnapshot, rid: str | None
) -> DownloadLink:
    if snapshot.pdf_status != PdfStatus.READY or not snapshot.pdf_public_id:
        raise Conflict(
            f"The PDF is {snapshot.pdf_status.value}"
            + (f": {snapshot.pdf_error}" if snapshot.pdf_error else "")
        )
    link = raw_download_url(snapshot.pdf_public_id)
    audit.record(
        db,
        org_id=snapshot.organization_id,
        principal=principal,
        action="report.pdf_downloaded",
        target_type="report",
        target_id=snapshot.report_id,
        data={"version": snapshot.version},
        request_id=rid,
    )
    await db.commit()
    return DownloadLink(url=link.url, expires_at=link.expires_at)


async def rerender_pdf(
    db: AsyncSession,
    principal: Principal,
    snapshot: ReportSnapshot,
    *,
    cloudinary_ready: bool,
    rid: str | None,
) -> SnapshotOut:
    if not cloudinary_ready:
        raise ServiceUnavailable("Cloudinary is not configured (set CLOUDINARY_URL)")
    if snapshot.pdf_status == PdfStatus.READY:
        raise Conflict("The PDF is already available")
    snapshot.pdf_status, snapshot.pdf_error = PdfStatus.PENDING, None
    audit.record(
        db,
        org_id=snapshot.organization_id,
        principal=principal,
        action="report.pdf_requested",
        target_type="report",
        target_id=snapshot.report_id,
        data={"version": snapshot.version},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(snapshot)
    _enqueue_pdf(snapshot.id)
    return (await _snapshot_outs(db, [snapshot]))[0]
