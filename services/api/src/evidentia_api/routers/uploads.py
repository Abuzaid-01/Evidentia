from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from evidentia_api.deps import CloudinaryDep, Contributor, RequestId, SettingsDep, TenantDB
from evidentia_api.schemas.assets import (
    AssetSummary,
    UploadConfirmRequest,
    UploadSignRequest,
    UploadSignResponse,
)
from evidentia_api.services import ingestion
from evidentia_api.services.assets import to_summary

router = APIRouter(prefix="/v1", tags=["uploads"])


@router.post("/uploads/sign", response_model=UploadSignResponse)
async def sign_upload(
    body: UploadSignRequest,
    principal: Contributor,
    db: TenantDB,
    settings: SettingsDep,
    creds: CloudinaryDep,
    rid: RequestId,
) -> UploadSignResponse:
    """Register an upload intent and return server-built, signed Cloudinary upload parameters.

    The browser POSTs the file plus `fields` directly to `upload_url` (chunked above `chunk_size`),
    then calls `/v1/assets/{asset_id}/confirm` with Cloudinary's response.
    """
    return await ingestion.sign_upload(db, principal, body, settings, creds, rid)


@router.post("/assets/{asset_id}/confirm", response_model=AssetSummary)
async def confirm_upload(
    asset_id: uuid.UUID,
    body: UploadConfirmRequest,
    principal: Contributor,
    db: TenantDB,
    settings: SettingsDep,
    creds: CloudinaryDep,
    rid: RequestId,
    request: Request,
) -> AssetSummary:
    """Confirm a finished upload. Verified with the signature in Cloudinary's upload response;
    idempotent with the upload webhook (whichever arrives first starts processing)."""
    asset = await ingestion.confirm_upload(
        db, principal, asset_id, body.public_id, body.version, body.signature, creds, rid
    )
    return to_summary(asset, settings, cloudinary_ready=request.app.state.cloudinary is not None)
