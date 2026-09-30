"""Delete a whole project: database rows now, Cloudinary files right after (worker task).

Evidence links are protected by RESTRICT foreign keys (so a photo or metric can't vanish from under
a claim by accident); a project deletion removes those links explicitly first, then deletes the
project row and lets ON DELETE CASCADE remove everything else. The audit event survives: it belongs
to the organisation, not the project.
"""

from __future__ import annotations

import json
import uuid

import structlog
from evidentia_core import tasks
from evidentia_core.db.models import (
    ActivityEvent,
    Asset,
    Claim,
    ClaimMetric,
    EvidenceLink,
    Job,
    Metric,
    Project,
    Report,
    ReportSnapshot,
)
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.errors import Unprocessable
from evidentia_api.schemas.projects import ProjectDeleteOut
from evidentia_api.services import audit
from evidentia_api.services.projects import get_project

log = structlog.get_logger("evidentia.projects")
_ENQUEUE_CHUNK = 500


async def delete_project(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    confirm_name: str,
    *,
    cloudinary_ready: bool,
    rid: str | None,
) -> ProjectDeleteOut:
    project = await get_project(db, project_id)
    if confirm_name.strip() != project.name:
        raise Unprocessable("Type the project's exact name to confirm the deletion")

    assets = (
        await db.execute(
            select(Asset.id, Asset.public_id, Asset.resource_type).where(
                Asset.project_id == project.id
            )
        )
    ).all()
    asset_ids = [a.id for a in assets]
    claim_ids = list(await db.scalars(select(Claim.id).where(Claim.project_id == project.id)))
    event_ids = list(
        await db.scalars(select(ActivityEvent.id).where(ActivityEvent.project_id == project.id))
    )
    metric_ids = list(await db.scalars(select(Metric.id).where(Metric.project_id == project.id)))
    pdfs = list(
        await db.scalars(
            select(ReportSnapshot.pdf_public_id)
            .join(Report, Report.id == ReportSnapshot.report_id)
            .where(Report.project_id == project.id, ReportSnapshot.pdf_public_id.is_not(None))
        )
    )
    reports = await db.scalar(
        select(func.count()).select_from(Report).where(Report.project_id == project.id)
    )

    # 1. the protected edges (RESTRICT) must go first
    await db.execute(
        delete(EvidenceLink).where(
            or_(
                EvidenceLink.claim_id.in_(claim_ids),
                EvidenceLink.event_id.in_(event_ids),
                EvidenceLink.asset_id.in_(asset_ids),
            )
        )
    )
    await db.execute(
        delete(ClaimMetric).where(
            or_(ClaimMetric.claim_id.in_(claim_ids), ClaimMetric.metric_id.in_(metric_ids))
        )
    )
    await db.execute(delete(Job).where(Job.target_id.in_(asset_ids)))
    # 2. the project; ON DELETE CASCADE removes sites, assets, observations, claims, reports...
    await db.execute(delete(Project).where(Project.id == project.id))

    media: dict[str, list[str]] = {"image": [], "video": [], "raw": list(pdfs)}
    for asset in assets:
        media[asset.resource_type.value].append(asset.public_id)
    files = sum(len(ids) for ids in media.values())
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="project.deleted",
        target_type="project",
        target_id=project.id,
        data={
            "name": project.name,
            "assets": len(assets),
            "claims": len(claim_ids),
            "reports": reports,
            "cloudinary_files": files,
        },
        request_id=rid,
    )
    await db.commit()

    queued = 0
    if cloudinary_ready and files:
        for resource_type, ids in media.items():
            for start in range(0, len(ids), _ENQUEUE_CHUNK):
                chunk = ids[start : start + _ENQUEUE_CHUNK]
                try:
                    tasks.enqueue(tasks.DELETE_CLOUDINARY_MEDIA, json.dumps({resource_type: chunk}))
                    queued += len(chunk)
                except Exception as exc:  # the database side is done; files can be cleaned later
                    log.warning("cloudinary_delete_enqueue_failed", error=str(exc))
    return ProjectDeleteOut(
        project_id=project.id,
        name=project.name,
        assets=len(assets),
        claims=len(claim_ids),
        reports=int(reports or 0),
        cloudinary_files_queued=queued,
    )
