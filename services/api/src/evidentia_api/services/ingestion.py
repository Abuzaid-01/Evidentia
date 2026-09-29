"""Upload signing, upload confirmation and the hand-off to the processing pipeline.

Two independent signals can report that Cloudinary stored an asset: the browser's confirm call
(fast, verified via Cloudinary's response signature) and the webhook (reliable, verified via the
notification signature). Both call `claim_upload`, which flips AWAITING_UPLOAD -> UPLOADED with a
single conditional UPDATE, so exactly one of them enqueues the pipeline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from evidentia_cloudinary import CloudinaryCredentials
from evidentia_cloudinary.upload import UploadSpec, create_signed_upload, verify_upload_response
from evidentia_core import tasks
from evidentia_core.config import Settings
from evidentia_core.db.models import Asset, Job
from evidentia_core.domain.enums import ActorKind, AssetState, JobState, ResourceType
from evidentia_core.domain.media_policy import MediaLimits, MediaRejected, check_declared
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.errors import AppError, NotFound, Unprocessable
from evidentia_api.schemas.assets import UploadSignRequest, UploadSignResponse
from evidentia_api.services import audit
from evidentia_api.services.projects import active_taxonomy, get_project, get_site

log = structlog.get_logger("evidentia.ingestion")


def media_limits(settings: Settings) -> MediaLimits:
    return MediaLimits(
        max_image_bytes=settings.max_image_bytes,
        max_video_bytes=settings.max_video_bytes,
        max_video_seconds=settings.max_video_seconds,
    )


async def sign_upload(
    session: AsyncSession,
    principal: Principal,
    body: UploadSignRequest,
    settings: Settings,
    creds: CloudinaryCredentials,
    request_id: str | None,
) -> UploadSignResponse:
    project = await get_project(session, body.project_id)
    if project.status != "active":
        raise Unprocessable("Uploads are closed for archived projects")
    if body.site_id:
        site = await get_site(session, body.site_id)
        if site.project_id != project.id:
            raise Unprocessable("Site does not belong to this project")
    if body.declared_activity:
        taxonomy = await active_taxonomy(session, project)
        keys = {a["key"] for a in taxonomy.activities}
        if body.declared_activity not in keys:
            raise Unprocessable(f"Unknown activity '{body.declared_activity}' for this project")

    try:
        resource_type = check_declared(body.content_type, body.size_bytes, media_limits(settings))
    except MediaRejected as exc:
        raise Unprocessable(str(exc), code="media_rejected") from exc

    asset_id = uuid.uuid4()
    asset = Asset(
        id=asset_id,
        organization_id=principal.org_id,
        project_id=project.id,
        site_id=body.site_id,
        uploaded_by_id=principal.user_id,
        declared_activity=body.declared_activity,
        declared_capture_time=body.captured_at,
        contributor_note=body.note,
        original_filename=body.filename,
        declared_mime=body.content_type,
        declared_bytes=body.size_bytes,
        resource_type=resource_type,
        public_id=str(asset_id),
        state=AssetState.AWAITING_UPLOAD,
        state_changed_at=datetime.now(UTC),
    )
    session.add(asset)

    preset = (
        settings.cloudinary_upload_preset_image
        if resource_type == ResourceType.IMAGE
        else settings.cloudinary_upload_preset_video
    )
    signed = create_signed_upload(
        UploadSpec(
            asset_id=asset_id,
            organization_id=principal.org_id,
            project_id=project.id,
            site_id=body.site_id,
            resource_type=resource_type.value,  # type: ignore[arg-type]
            uploaded_by=principal.user_id,
            folder_root=settings.cloudinary_folder_root,
            original_filename=body.filename,
            declared_activity=body.declared_activity,
            contributor_note=body.note,
            notification_url=settings.webhook_url,
            upload_preset=preset,
            use_named_transformations=settings.cloudinary_use_named_transformations,
            use_structured_metadata=settings.cloudinary_use_structured_metadata,
        ),
        creds,
    )
    asset.asset_folder = signed.fields.get("asset_folder")
    audit.record(
        session,
        org_id=principal.org_id,
        principal=principal,
        action="asset.upload_signed",
        target_type="asset",
        target_id=asset_id,
        data={"filename": body.filename, "bytes": body.size_bytes, "type": resource_type.value},
        request_id=request_id,
    )
    await session.commit()
    return UploadSignResponse(
        asset_id=asset_id,
        resource_type=resource_type,
        upload_url=signed.upload_url,
        fields=signed.fields,
        chunk_size=settings.upload_chunk_bytes,
        expires_at=signed.expires_at,
    )


async def claim_upload(
    session: AsyncSession,
    asset: Asset,
    *,
    version: int | None,
    source: str,
    principal: Principal | None = None,
    request_id: str | None = None,
) -> bool:
    """Atomically mark an asset as stored and create its pipeline job. Returns True if we won."""
    now = datetime.now(UTC)
    result = await session.execute(
        update(Asset)
        .where(Asset.id == asset.id, Asset.state == AssetState.AWAITING_UPLOAD)
        .values(
            state=AssetState.UPLOADED,
            state_changed_at=now,
            state_reason=f"confirmed via {source}",
            cloudinary_version=version,
        )
        .returning(Asset.id)
    )
    if result.scalar_one_or_none() is None:
        return False

    await session.execute(
        insert(Job)
        .values(
            organization_id=asset.organization_id,
            type=tasks.PROCESS_ASSET,
            target_type="asset",
            target_id=asset.id,
            run_key=f"pipeline:{asset.id}:{asset.analysis_generation}",
            state=JobState.QUEUED,
        )
        .on_conflict_do_nothing(index_elements=[Job.run_key])
    )
    audit.record(
        session,
        org_id=asset.organization_id,
        principal=principal,
        actor_kind=ActorKind.USER if principal else ActorKind.WEBHOOK,
        action="asset.uploaded",
        target_type="asset",
        target_id=asset.id,
        data={"source": source, "version": version},
        request_id=request_id,
    )
    return True


def enqueue_pipeline(asset_id: uuid.UUID) -> None:
    """Call only AFTER the claim is committed, so the worker can see the row."""
    try:
        tasks.enqueue(tasks.PROCESS_ASSET, str(asset_id))
    except Exception:  # broker down: the asset stays UPLOADED and the sweeper re-enqueues it
        log.exception("enqueue_failed", asset_id=str(asset_id))


async def confirm_upload(
    session: AsyncSession,
    principal: Principal,
    asset_id: uuid.UUID,
    public_id: str,
    version: int,
    signature: str,
    creds: CloudinaryCredentials,
    request_id: str | None,
) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise NotFound("Asset not found")
    if public_id != asset.public_id:
        raise AppError("public_id does not match this asset", code="public_id_mismatch")
    if not verify_upload_response(public_id, version, signature, creds):
        raise AppError("Upload signature is not valid", code="invalid_upload_signature")

    claimed = await claim_upload(
        session,
        asset,
        version=version,
        source="browser",
        principal=principal,
        request_id=request_id,
    )
    await session.commit()
    if claimed:
        enqueue_pipeline(asset.id)
    await session.refresh(asset)
    return asset
