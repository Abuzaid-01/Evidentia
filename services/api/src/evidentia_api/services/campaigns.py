"""Phase 8: Campaign Studio, lineage tracing, and external share links."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from evidentia_cloudinary.campaign import (
    ReelSegment,
    signed_campaign_url,
    social_card_transformation,
    video_reel_transformation,
)
from evidentia_cloudinary.delivery import rendition_url
from evidentia_core.config import Settings
from evidentia_core.db.models import (
    Asset,
    BeforeAfterPair,
    Campaign,
    Claim,
    Derivative,
    EvidenceLink,
    Metric,
    Project,
    Report,
    ReportSnapshot,
    ShareLink,
)
from evidentia_core.domain.enums import AssetState, PairStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.errors import Conflict, NotFound, Unprocessable
from evidentia_api.schemas.campaigns import (
    CampaignCreate,
    CampaignOut,
    LineageDerivativeOut,
    LineageOut,
    SharedContentOut,
    ShareLinkCreate,
    ShareLinkOut,
    SocialRenditionOut,
    VideoReelCreate,
    VideoReelOut,
)
from evidentia_api.services import audit
from evidentia_api.services.projects import get_project

LINKABLE_ASSET_STATES = {AssetState.READY, AssetState.INDEXED}


async def create_campaign(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    body: CampaignCreate,
    settings: Settings,
) -> CampaignOut:
    """Create social campaign card renditions for an approved asset or before/after pair."""
    await get_project(db, project_id)  # 404 if missing or another tenant's

    # 1. Validate the source asset
    asset = await db.get(Asset, body.asset_id)
    if asset is None or asset.project_id != project_id:
        raise NotFound("Evidence asset not found in this project")
    if asset.state not in LINKABLE_ASSET_STATES:
        raise Unprocessable(
            f"Asset is '{asset.state.value}'; only ready or indexed evidence can be used in campaigns"
        )

    # 2. Validate optional before/after pair
    if body.pair_id:
        pair = await db.get(BeforeAfterPair, body.pair_id)
        if pair is None or pair.project_id != project_id:
            raise NotFound("Before/after pair not found")
        if pair.status != PairStatus.CONFIRMED:
            raise Unprocessable("Only confirmed before/after pairs can be used in campaigns")

    # 3. Validate optional claim
    if body.claim_id:
        claim = await db.get(Claim, body.claim_id)
        if claim is None or claim.project_id != project_id:
            raise NotFound("Claim not found")

    # 4. Validate optional metric
    if body.metric_id:
        metric = await db.get(Metric, body.metric_id)
        if metric is None or metric.project_id != project_id:
            raise NotFound("Metric not found")

    # 5. Generate renditions for each requested format
    renditions: dict[str, Any] = {}
    any_generative = False

    for fmt in body.formats:
        trans, is_gen = social_card_transformation(
            aspect_ratio=fmt,  # type: ignore[arg-type]
            headline=body.headline,
            stat_text=body.stat_text,
            brand_name=body.brand_tag,
            redact=body.redact,
            generative_fill=body.generative_fill,
            generative_restore=body.generative_restore,
        )
        if is_gen:
            any_generative = True

        named_trans = f"ev_social_{fmt.replace(':', 'x')}{'_redacted' if body.redact else ''}"
        purpose = f"campaign_{fmt.replace(':', 'x')}"

        delivery = signed_campaign_url(
            asset.public_id,
            trans,
            format="jpg",
            variant=purpose,
        )

        # Record in derivatives table for audit and lineage
        deriv = Derivative(
            organization_id=principal.org_id,
            asset_id=asset.id,
            purpose=purpose,
            named_transformation=named_trans,
            transformation=trans,
            format="jpg",
            source="campaign_studio",
            generative=is_gen,
            created_by_id=principal.user_id,
        )
        db.add(deriv)

        renditions[fmt] = {
            "format": fmt,
            "url": delivery.url,
            "transformation": trans,
            "named_transformation": named_trans,
            "generative": is_gen,
            "purpose": purpose,
        }

    # 6. Save Campaign record
    campaign = Campaign(
        organization_id=principal.org_id,
        project_id=project_id,
        title=body.title,
        headline=body.headline,
        stat_text=body.stat_text,
        brand_tag=body.brand_tag,
        asset_id=asset.id,
        pair_id=body.pair_id,
        claim_id=body.claim_id,
        metric_id=body.metric_id,
        formats=body.formats,
        generative=any_generative,
        renditions=renditions,
        created_by_id=principal.user_id,
    )
    db.add(campaign)
    await db.flush()

    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="campaign.created",
        target_type="campaign",
        target_id=campaign.id,
        data={
            "project_id": str(project_id),
            "asset_id": str(asset.id),
            "formats": body.formats,
            "generative": any_generative,
            "redact": body.redact,
        },
    )

    return _campaign_to_out(campaign)


def _campaign_to_out(c: Campaign) -> CampaignOut:
    renditions_out = {
        k: SocialRenditionOut(
            format=v["format"],
            url=v["url"],
            transformation=v["transformation"],
            named_transformation=v.get("named_transformation"),
            generative=v.get("generative", False),
            purpose=v["purpose"],
        )
        for k, v in c.renditions.items()
    }
    return CampaignOut(
        id=c.id,
        project_id=c.project_id,
        title=c.title,
        headline=c.headline,
        stat_text=c.stat_text,
        brand_tag=c.brand_tag,
        asset_id=c.asset_id,
        pair_id=c.pair_id,
        claim_id=c.claim_id,
        metric_id=c.metric_id,
        formats=c.formats,
        generative=c.generative,
        renditions=renditions_out,
        created_at=c.created_at,
    )


async def list_campaigns(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> list[CampaignOut]:
    """List all campaigns for a project."""
    await get_project(db, project_id)
    query = (
        select(Campaign)
        .where(Campaign.project_id == project_id)
        .order_by(Campaign.created_at.desc())
    )
    campaigns = (await db.scalars(query)).all()
    return [_campaign_to_out(c) for c in campaigns]


async def get_campaign(
    db: AsyncSession,
    campaign_id: uuid.UUID,
) -> CampaignOut:
    """Fetch a single campaign by ID."""
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise NotFound("Campaign not found")
    return _campaign_to_out(campaign)


async def create_video_reel(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    body: VideoReelCreate,
    settings: Settings,
) -> VideoReelOut:
    """Create a spliced video highlight reel from cited segments with fl_splice."""
    await get_project(db, project_id)

    reel_segments: list[ReelSegment] = []
    total_seconds = 0.0
    first_asset: Asset | None = None

    for seg in body.segments:
        asset = await db.get(Asset, seg.asset_id)
        if asset is None or asset.project_id != project_id:
            raise NotFound(f"Asset {seg.asset_id} not found in this project")
        if asset.resource_type.value != "video":
            raise Unprocessable(f"Asset {seg.asset_id} is not a video")

        if first_asset is None:
            first_asset = asset

        start_s = max(0.0, seg.start_ms / 1000.0)
        end_s = max(start_s + 0.5, seg.end_ms / 1000.0)
        total_seconds += end_s - start_s

        reel_segments.append(
            ReelSegment(
                public_id=asset.public_id,
                start_s=start_s,
                end_s=end_s,
                caption=seg.caption,
            )
        )

    if first_asset is None:
        raise Unprocessable("At least one video segment is required")

    trans = video_reel_transformation(reel_segments, redact=body.redact)
    delivery = signed_campaign_url(
        first_asset.public_id,
        trans,
        resource_type="video",
        format="mp4",
        variant="campaign_reel",
    )

    deriv = Derivative(
        organization_id=principal.org_id,
        asset_id=first_asset.id,
        purpose="campaign_reel",
        named_transformation=None,
        transformation=trans,
        format="mp4",
        source="campaign_studio",
        generative=False,
        created_by_id=principal.user_id,
    )
    db.add(deriv)
    await db.flush()

    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="campaign.video_reel_created",
        target_type="derivative",
        target_id=deriv.id,
        data={
            "project_id": str(project_id),
            "segments_count": len(reel_segments),
            "duration_seconds": round(total_seconds, 2),
            "redact": body.redact,
        },
    )

    return VideoReelOut(
        id=deriv.id,
        title=body.title,
        url=delivery.url,
        transformation=trans,
        segments_count=len(reel_segments),
        duration_seconds=round(total_seconds, 2),
        created_at=deriv.created_at,
    )


async def get_asset_lineage(
    db: AsyncSession,
    asset_id: uuid.UUID,
    settings: Settings,
) -> LineageOut:
    """Return the complete provenance and transformation lineage for an asset."""
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise NotFound("Asset not found")

    # Fetch all derivatives for this asset
    derivs = (
        await db.scalars(
            select(Derivative)
            .where(Derivative.asset_id == asset.id)
            .order_by(Derivative.created_at.asc())
        )
    ).all()

    deriv_outs: list[LineageDerivativeOut] = []
    for d in derivs:
        url_obj = signed_campaign_url(
            asset.public_id,
            d.transformation,
            resource_type=asset.resource_type.value,
            format=d.format or "jpg",
            variant=d.purpose,
        )
        deriv_outs.append(
            LineageDerivativeOut(
                id=d.id,
                purpose=d.purpose,
                named_transformation=d.named_transformation,
                transformation=d.transformation,
                format=d.format,
                source=d.source,
                generative=d.generative,
                url=url_obj.url,
                created_at=d.created_at,
            )
        )

    # Fetch before/after pairs involving this asset
    pairs_query = select(BeforeAfterPair).where(
        (BeforeAfterPair.before_asset_id == asset.id) | (BeforeAfterPair.after_asset_id == asset.id)
    )
    pairs = (await db.scalars(pairs_query)).all()
    pairs_data = [
        {
            "id": str(p.id),
            "role": "before" if p.before_asset_id == asset.id else "after",
            "status": p.status.value,
            "rank_score": p.rank_score,
            "change_summary": p.change_summary,
        }
        for p in pairs
    ]

    # Fetch claims citing this asset
    links_query = (
        select(EvidenceLink, Claim)
        .join(Claim, EvidenceLink.claim_id == Claim.id)
        .where(EvidenceLink.asset_id == asset.id)
    )
    claim_rows = (await db.execute(links_query)).all()
    claims_data = [
        {
            "claim_id": str(c.id),
            "statement": c.statement,
            "status": c.status.value,
            "relation": link.relation.value,
        }
        for link, c in claim_rows
    ]

    # Fetch campaigns created from this asset
    campaigns_query = select(Campaign).where(Campaign.asset_id == asset.id)
    campaigns = (await db.scalars(campaigns_query)).all()
    campaigns_data = [
        {
            "campaign_id": str(c.id),
            "title": c.title,
            "headline": c.headline,
            "formats": c.formats,
            "generative": c.generative,
        }
        for c in campaigns
    ]

    return LineageOut(
        asset_id=asset.id,
        original_filename=asset.original_filename,
        public_id=asset.public_id,
        format=asset.format,
        bytes=asset.bytes,
        sha256=asset.sha256,
        phash=str(asset.phash) if asset.phash is not None else None,
        capture_time=asset.capture_time,
        capture_time_source=asset.capture_time_source.value,
        uploaded_at=asset.uploaded_at,
        derivatives=deriv_outs,
        pairs=pairs_data,
        claims=claims_data,
        campaigns=campaigns_data,
    )


# --- Share Links ---------------------------------------------------------------------------------


async def create_share_link(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    body: ShareLinkCreate,
) -> ShareLinkOut:
    """Create an external read-only share link."""
    await get_project(db, project_id)

    # Validate target exists
    if body.target_type == "report":
        target = await db.get(Report, body.target_id) or await db.get(
            ReportSnapshot, body.target_id
        )
        if target is None:
            raise NotFound("Report target not found")
    elif body.target_type == "evidence":
        target = await db.get(Asset, body.target_id)
        if target is None:
            raise NotFound("Asset evidence target not found")
    elif body.target_type == "campaign":
        target = await db.get(Campaign, body.target_id)
        if target is None:
            raise NotFound("Campaign target not found")
    else:
        raise Unprocessable(f"Unsupported target_type: {body.target_type}")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days)

    link = ShareLink(
        organization_id=principal.org_id,
        project_id=project_id,
        token=token,
        title=body.title,
        target_type=body.target_type,
        target_id=body.target_id,
        expires_at=expires_at,
        created_by_id=principal.user_id,
    )
    db.add(link)
    await db.flush()

    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="share_link.created",
        target_type="share_link",
        target_id=link.id,
        data={
            "project_id": str(project_id),
            "target_type": body.target_type,
            "target_id": str(body.target_id),
            "expires_at": expires_at.isoformat(),
        },
    )

    return _share_to_out(link)


def _share_to_out(link: ShareLink) -> ShareLinkOut:
    return ShareLinkOut(
        id=link.id,
        project_id=link.project_id,
        token=link.token,
        title=link.title,
        target_type=link.target_type,
        target_id=link.target_id,
        share_url=f"/share/{link.token}",
        expires_at=link.expires_at,
        view_count=link.view_count,
        is_revoked=link.is_revoked,
        created_at=link.created_at,
    )


async def list_share_links(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> list[ShareLinkOut]:
    """List all share links for a project."""
    await get_project(db, project_id)
    query = (
        select(ShareLink)
        .where(ShareLink.project_id == project_id)
        .order_by(ShareLink.created_at.desc())
    )
    links = (await db.scalars(query)).all()
    return [_share_to_out(link) for link in links]


async def revoke_share_link(
    db: AsyncSession,
    principal: Principal,
    link_id: uuid.UUID,
) -> None:
    """Revoke an active share link."""
    link = await db.get(ShareLink, link_id)
    if link is None:
        raise NotFound("Share link not found")
    link.is_revoked = True
    await db.flush()

    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="share_link.revoked",
        target_type="share_link",
        target_id=link.id,
    )


async def resolve_shared_content(
    db: AsyncSession,
    token: str,
    settings: Settings,
) -> SharedContentOut:
    """Public resolver for shared links. Enforces mandatory face redaction and strips precise GPS."""
    # Find share link
    link = await db.scalar(select(ShareLink).where(ShareLink.token == token))
    if link is None or link.is_revoked:
        raise NotFound("This share link does not exist or has been revoked")

    if link.expires_at < datetime.now(UTC):
        raise Conflict("This share link has expired")

    # Increment view count
    link.view_count += 1
    link.last_viewed_at = datetime.now(UTC)

    project = await db.get(Project, link.project_id)
    project_name = project.name if project else "Project"

    data: dict[str, Any] = {}
    lineage_records: list[dict[str, Any]] = []

    if link.target_type == "report":
        # Report or ReportSnapshot
        snapshot = await db.get(ReportSnapshot, link.target_id)
        if snapshot is None:
            # Maybe it's a report ID, fetch latest snapshot
            snapshot = await db.scalar(
                select(ReportSnapshot)
                .where(ReportSnapshot.report_id == link.target_id)
                .order_by(ReportSnapshot.version.desc())
                .limit(1)
            )
        if snapshot is None:
            raise NotFound("Shared report snapshot not found")

        # Never the internal record: a privacy-redacted public view of the published report
        from evidentia_api.services.reports import public_report_view

        data = await public_report_view(
            db, snapshot, settings, cloudinary_ready=settings.cloudinary_configured
        )

    elif link.target_type == "evidence":
        asset = await db.get(Asset, link.target_id)
        if asset is None:
            raise NotFound("Shared evidence asset not found")

        # MANDATORY REDACTION: Use public_redacted URL ONLY! Never unredacted original!
        redacted_delivery = rendition_url(
            asset.public_id,
            asset.resource_type.value,
            "public_redacted",
            use_named=settings.cloudinary_use_named_transformations,
        )

        # Precise GPS stripped: site only
        data = {
            "asset_id": str(asset.id),
            "media_url": redacted_delivery.url,
            "resource_type": asset.resource_type.value,
            "format": asset.format,
            "caption": asset.caption,
            "verified_activities": asset.verified_activities or [],
            "capture_time": asset.capture_time.isoformat() if asset.capture_time else None,
            "redacted": True,
        }

        # Lineage derivatives
        lineage_obj = await get_asset_lineage(db, asset.id, settings)
        lineage_records = [d.model_dump(mode="json") for d in lineage_obj.derivatives]

    elif link.target_type == "campaign":
        campaign = await db.get(Campaign, link.target_id)
        if campaign is None:
            raise NotFound("Shared campaign not found")

        data = {
            "campaign_id": str(campaign.id),
            "title": campaign.title,
            "headline": campaign.headline,
            "stat_text": campaign.stat_text,
            "brand_tag": campaign.brand_tag,
            "formats": campaign.formats,
            "generative": campaign.generative,
            "renditions": campaign.renditions,
        }

    await db.flush()

    return SharedContentOut(
        token=link.token,
        title=link.title,
        target_type=link.target_type,
        project_name=project_name,
        expires_at=link.expires_at,
        data=data,
        lineage=lineage_records,
    )
