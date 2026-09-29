"""Phase 8: Campaign Studio and share links router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from evidentia_api.deps import Manager, SettingsDep, TenantDB, Viewer
from evidentia_api.schemas.campaigns import (
    CampaignCreate,
    CampaignOut,
    ShareLinkCreate,
    ShareLinkOut,
    VideoReelCreate,
    VideoReelOut,
)
from evidentia_api.services import campaigns as svc

router = APIRouter(prefix="/v1", tags=["campaigns"])


@router.post(
    "/projects/{project_id}/campaigns",
    response_model=CampaignOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign(
    project_id: uuid.UUID,
    body: CampaignCreate,
    principal: Manager,
    db: TenantDB,
    settings: SettingsDep,
) -> CampaignOut:
    """Generate social format campaign cards (1:1, 4:5, 9:16, 16:9) with mandatory redaction."""
    campaign = await svc.create_campaign(db, principal, project_id, body, settings)
    await db.commit()
    return campaign


@router.get(
    "/projects/{project_id}/campaigns",
    response_model=list[CampaignOut],
)
async def list_campaigns(
    project_id: uuid.UUID,
    _: Viewer,
    db: TenantDB,
) -> list[CampaignOut]:
    """List all generated campaigns for a project."""
    return await svc.list_campaigns(db, project_id)


@router.get(
    "/campaigns/{campaign_id}",
    response_model=CampaignOut,
)
async def get_campaign(
    campaign_id: uuid.UUID,
    _: Viewer,
    db: TenantDB,
) -> CampaignOut:
    """Fetch details and signed URLs for a campaign."""
    return await svc.get_campaign(db, campaign_id)


@router.post(
    "/projects/{project_id}/campaigns/video-reel",
    response_model=VideoReelOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_video_reel(
    project_id: uuid.UUID,
    body: VideoReelCreate,
    principal: Manager,
    db: TenantDB,
    settings: SettingsDep,
) -> VideoReelOut:
    """Create a highlight reel stitched from cited video segments with fl_splice."""
    reel = await svc.create_video_reel(db, principal, project_id, body, settings)
    await db.commit()
    return reel


# --- Share Links ---------------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/share-links",
    response_model=ShareLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_share_link(
    project_id: uuid.UUID,
    body: ShareLinkCreate,
    principal: Manager,
    db: TenantDB,
) -> ShareLinkOut:
    """Create an external read-only share link."""
    link = await svc.create_share_link(db, principal, project_id, body)
    await db.commit()
    return link


@router.get(
    "/projects/{project_id}/share-links",
    response_model=list[ShareLinkOut],
)
async def list_share_links(
    project_id: uuid.UUID,
    _: Viewer,
    db: TenantDB,
) -> list[ShareLinkOut]:
    """List all active and historical share links for a project."""
    return await svc.list_share_links(db, project_id)


@router.delete(
    "/share-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_share_link(
    link_id: uuid.UUID,
    principal: Manager,
    db: TenantDB,
) -> None:
    """Revoke an active share link immediately."""
    await svc.revoke_share_link(db, principal, link_id)
    await db.commit()
