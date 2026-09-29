"""Demo mode: the full evidence workflow in single calls, for live presentations.

Nothing is simulated. Each step calls the same services the regular screens use: real Cloudinary
write-back after review, real AI validation and narrative, the real PDF worker. The only shortcut
is who clicks. Approvals are made by a separate, clearly named "Demo reviewer" user in the caller's
organisation, so the four-eyes rule and the audit trail stay intact ("approved by Demo reviewer").

A claim the AI validator says is NOT supported is never approved automatically: it is left in
review for a human, exactly as in the full workflow.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from evidentia_ai.text_llm import TextLLM
from evidentia_core.config import Settings
from evidentia_core.db.models import Asset, Observation
from evidentia_core.domain.claims import numbers_in
from evidentia_core.domain.enums import (
    AssetState,
    ClaimStatus,
    ObservationStatus,
    OntologyType,
    ReviewDecision,
    Role,
    ValidationVerdict,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Identity, Principal
from evidentia_api.auth.provisioning import resolve_principal
from evidentia_api.errors import NotFound, ServiceUnavailable, Unprocessable
from evidentia_api.schemas.claims import ClaimCreate, DecisionBody, EvidenceLinkCreate
from evidentia_api.schemas.demo import DemoClaimIn, DemoClaimOut, DemoReportIn, DemoReportOut
from evidentia_api.schemas.reports import ReportCreate
from evidentia_api.schemas.review import DecisionIn, ReviewRequest
from evidentia_api.services import claims as claims_svc
from evidentia_api.services import reports as reports_svc
from evidentia_api.services import review as review_svc

DEMO_REVIEWER_NAME = "Demo reviewer"
_USABLE = {AssetState.READY, AssetState.REVIEW_REQUIRED}
# what the demo reviewer approves: what the photo shows, not quality/sensitivity flags
_APPROVABLE = {
    OntologyType.ACTIVITY,
    OntologyType.OBJECT,
    OntologyType.CONDITION,
    OntologyType.PEOPLE,
    OntologyType.SCENE,
}
# evidence linked to the claim, strongest first
_EVIDENCE_ORDER = {OntologyType.CONDITION: 0, OntologyType.ACTIVITY: 1, OntologyType.OBJECT: 2}
_MAX_LINKS = 3


def require_enabled(settings: Settings) -> None:
    if not settings.demo_mode_enabled:
        raise ServiceUnavailable("Demo mode is turned off (DEMO_MODE_ENABLED=false)")


async def demo_reviewer(principal: Principal) -> Principal:
    """A real, separate reviewer account in the caller's organisation (created on first use)."""
    return await resolve_principal(
        Identity(
            external_user_id=f"demo_reviewer:{principal.external_org_id}",
            external_org_id=principal.external_org_id,
            token_role=Role.REVIEWER,
            display_name=DEMO_REVIEWER_NAME,
        )
    )


def _default_statement(caption: str | None) -> str:
    """The AI caption, minus bare numbers: a claim may only state numbers backed by a metric."""
    text = (caption or "").strip()
    for raw in numbers_in(text):
        text = re.sub(rf"(?<![\w.]){re.escape(raw)}%?(?![\w])", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;")
    if len(text) < 5:
        raise Unprocessable("This photo has no AI caption yet: type the claim yourself")
    return text[:2000]


async def make_claim(
    db: AsyncSession,
    principal: Principal,
    asset_id: uuid.UUID,
    body: DemoClaimIn,
    settings: Settings,
    llms: list[TextLLM],
    *,
    cloudinary_ready: bool,
    rid: str | None,
) -> DemoClaimOut:
    """Photo -> reviewed observations -> claim with evidence -> validated -> approved."""
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise NotFound("Asset not found")
    if asset.state not in _USABLE:
        raise Unprocessable(f"This photo is still '{asset.state.value}'; wait until it is ready")
    reviewer = await demo_reviewer(principal)
    steps: list[str] = []

    # 1. review: approve what the AI saw (the presenter is looking at it on screen)
    observations = (
        await db.scalars(select(Observation).where(Observation.asset_id == asset.id))
    ).all()
    to_approve = [
        o.id
        for o in observations
        if o.status == ObservationStatus.PROPOSED and o.ontology_type in _APPROVABLE
    ]
    if to_approve or asset.reviewed_at is None:
        await review_svc.apply_review(
            db,
            reviewer,
            asset.id,
            ReviewRequest(
                decisions=[
                    DecisionIn(observation_id=i, decision=ReviewDecision.APPROVE)
                    for i in to_approve
                ],
                complete=True,
                note="Demo mode review",
            ),
            settings,
            rid,
        )
    steps.append(f"{DEMO_REVIEWER_NAME} verified {len(to_approve)} AI observation(s)")

    # 2. claim, written by the caller
    statement = body.statement or _default_statement(asset.caption)
    claim = await claims_svc.create_claim(
        db,
        principal,
        asset.project_id,
        ClaimCreate(statement=statement, claim_type=body.claim_type, site_id=asset.site_id),
        rid,
    )
    steps.append(f"Claim written by {principal.display_name or 'you'}")

    # 3. evidence: the strongest verified observations, or the reviewed photo as a whole
    verified = sorted(
        (
            o
            for o in (
                await db.scalars(
                    select(Observation).where(
                        Observation.asset_id == asset.id,
                        Observation.status == ObservationStatus.VERIFIED,
                        Observation.ontology_type.in_(list(_EVIDENCE_ORDER)),
                    )
                )
            ).all()
            if not (o.ontology_type == OntologyType.ACTIVITY and o.subject == "other")
        ),
        key=lambda o: (_EVIDENCE_ORDER[o.ontology_type], -(o.confidence or 0), str(o.id)),
    )[:_MAX_LINKS]
    for obs in verified or [None]:
        await claims_svc.add_evidence(
            db,
            principal,
            claim.id,
            EvidenceLinkCreate(asset_id=asset.id, observation_id=obs.id if obs else None),
            rid,
        )
    linked = max(1, len(verified))
    for metric_id in body.metric_ids:
        await claims_svc.set_metric_link(db, principal, claim.id, metric_id, linked=True, rid=rid)
    steps.append(f"Linked {linked} piece(s) of photo evidence")

    # 4. rules + AI validation, then submit
    claim = await claims_svc.validate(db, principal, claim.id, llms, rid)
    verdict = claim.validation_verdict
    steps.append(f"AI validation: {verdict.value if verdict else 'not run'}")
    if not (claim.rule_check or {}).get("passed"):
        problems = "; ".join((claim.rule_check or {}).get("problems", []))
        detail = await claims_svc.claim_detail(
            db, claim, settings, cloudinary_ready=cloudinary_ready
        )
        return DemoClaimOut(
            claim=detail,
            approved=False,
            reviewed_observations=len(to_approve),
            linked_evidence=linked,
            validation_verdict=verdict,
            reviewer=DEMO_REVIEWER_NAME,
            steps=steps,
            message=f"The claim was kept as a draft: {problems}",
        )
    claim = await claims_svc.transition(
        db, principal, claim.id, ClaimStatus.IN_REVIEW, DecisionBody(), rid
    )
    steps.append("Submitted for review")

    # 5. four-eyes approval by the separate demo reviewer (never over a "not supported" verdict)
    message = None
    if verdict == ValidationVerdict.NOT_SUPPORTED:
        message = (
            "The AI validator says the photos do not support this claim, so it was left in "
            "review. Open the claim to read why, then edit it or approve it with a note."
        )
    else:
        claim = await claims_svc.transition(
            db,
            reviewer,
            claim.id,
            ClaimStatus.APPROVED,
            DecisionBody(note=f"Approved in demo mode by {DEMO_REVIEWER_NAME}"),
            rid,
        )
        steps.append(f"Approved by {DEMO_REVIEWER_NAME} (a second person: four-eyes rule)")
    detail = await claims_svc.claim_detail(db, claim, settings, cloudinary_ready=cloudinary_ready)
    return DemoClaimOut(
        claim=detail,
        approved=claim.status == ClaimStatus.APPROVED,
        reviewed_observations=len(to_approve),
        linked_evidence=linked,
        validation_verdict=verdict,
        reviewer=DEMO_REVIEWER_NAME,
        steps=steps,
        message=message,
    )


async def fast_track_claim(
    db: AsyncSession,
    principal: Principal,
    claim_id: uuid.UUID,
    settings: Settings,
    llms: list[TextLLM],
    *,
    cloudinary_ready: bool,
    rid: str | None,
) -> DemoClaimOut:
    """An existing claim: validate if needed, submit if draft, approve by the demo reviewer."""
    claim = await claims_svc.get_claim(db, claim_id)
    if claim.status in {ClaimStatus.APPROVED, ClaimStatus.RETRACTED}:
        raise Unprocessable(f"This claim is already {claim.status.value}")
    reviewer = await demo_reviewer(principal)
    steps: list[str] = []
    if claim.validated_at is None:
        claim = await claims_svc.validate(db, principal, claim.id, llms, rid)
        steps.append(
            f"AI validation: {claim.validation_verdict.value if claim.validation_verdict else '-'}"
        )
    if claim.status in {ClaimStatus.DRAFT, ClaimStatus.REJECTED}:
        if claim.status == ClaimStatus.REJECTED:
            claim = await claims_svc.transition(
                db, principal, claim.id, ClaimStatus.DRAFT, DecisionBody(), rid
            )
        claim = await claims_svc.transition(
            db, principal, claim.id, ClaimStatus.IN_REVIEW, DecisionBody(), rid
        )
        steps.append("Submitted for review")
    message = None
    if claim.validation_verdict == ValidationVerdict.NOT_SUPPORTED:
        message = "The AI validator says this claim is not supported; it was left in review."
    else:
        claim = await claims_svc.transition(
            db,
            reviewer,
            claim.id,
            ClaimStatus.APPROVED,
            DecisionBody(note=f"Approved in demo mode by {DEMO_REVIEWER_NAME}"),
            rid,
        )
        steps.append(f"Approved by {DEMO_REVIEWER_NAME} (four-eyes rule)")
    detail = await claims_svc.claim_detail(db, claim, settings, cloudinary_ready=cloudinary_ready)
    return DemoClaimOut(
        claim=detail,
        approved=claim.status == ClaimStatus.APPROVED,
        reviewed_observations=0,
        linked_evidence=len(detail.evidence),
        validation_verdict=claim.validation_verdict,
        reviewer=DEMO_REVIEWER_NAME,
        steps=steps,
        message=message,
    )


async def publish_report(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    body: DemoReportIn,
    settings: Settings,
    llms: list[TextLLM],
    *,
    cloudinary_ready: bool,
    rid: str | None,
) -> DemoReportOut:
    """Every approved claim -> report -> AI narrative (citation-checked) -> published + PDF."""
    title = body.title or f"Evidence report, {datetime.now(UTC).strftime('%d %b %Y %H:%M')}"
    report = await reports_svc.create_report(
        db, principal, project_id, ReportCreate(title=title, audience=body.audience), rid
    )
    if not report.claim_ids:
        raise Unprocessable("There are no approved claims yet: make a claim from a photo first")
    steps = [f"Report created with {len(report.claim_ids)} approved claim(s)"]
    report = await reports_svc.generate_narrative(db, principal, report.id, llms, rid)
    meta = report.narrative_meta or {}
    sentences = sum(len(v) for v in (report.narrative or {}).values())
    steps.append(
        f"Narrative written ({meta.get('mode')}"
        + (f", {meta.get('model')}" if meta.get("model") else "")
        + f"): {sentences} cited sentence(s)"
    )
    snapshot = await reports_svc.publish(
        db, principal, report.id, settings, cloudinary_ready=cloudinary_ready, rid=rid
    )
    steps.append(f"Published version {snapshot.version}; PDF is being printed into Cloudinary")
    return DemoReportOut(
        report_id=report.id,
        snapshot=snapshot,
        claims=len(report.claim_ids),
        narrative_mode=meta.get("mode"),
        sentences=sentences,
        rejected_sentences=len(meta.get("rejected") or []),
        steps=steps,
    )
