"""Server-built, signed direct uploads.

The browser uploads bytes straight to Cloudinary (our servers never proxy media), but **every
parameter is decided by the server** and covered by the signature. The client cannot change the
folder, delivery type, public_id or context without invalidating the signature.

Why not sign whatever the Upload Widget sends? Because then a client could pick its own folder,
make an asset public, or overwrite someone else's public_id. See PLAN.md §2 correction #11.
"""

from __future__ import annotations

import hmac
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

import cloudinary.utils

from evidentia_cloudinary.config import CloudinaryCredentials
from evidentia_cloudinary.transformations import eager_param

ResourceType = Literal["image", "video"]
UPLOAD_ENDPOINT = "https://api.cloudinary.com/v1_1/{cloud}/{resource_type}/upload"

# Parameters excluded from signatures, per Cloudinary's signing rules.
_UNSIGNED = frozenset({"file", "cloud_name", "resource_type", "api_key"})


@dataclass(frozen=True)
class UploadSpec:
    asset_id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    resource_type: ResourceType
    uploaded_by: uuid.UUID
    folder_root: str
    original_filename: str | None = None
    declared_activity: str | None = None
    contributor_note: str | None = None
    notification_url: str | None = None
    upload_preset: str | None = None
    use_named_transformations: bool = True
    use_structured_metadata: bool = False
    extra_tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SignedUpload:
    upload_url: str
    fields: dict[str, str]  # POST these as multipart fields alongside `file`
    public_id: str
    expires_at: int  # Cloudinary rejects signatures older than ~1 hour


def asset_folder(spec: UploadSpec) -> str:
    site = f"site_{spec.site_id}" if spec.site_id else "site_unassigned"
    return f"{spec.folder_root}/org_{spec.organization_id}/proj_{spec.project_id}/{site}"


def _sanitize_context_value(value: str, limit: int = 250) -> str:
    # Context values are free text; strip control chars and bound the length.
    cleaned = "".join(ch for ch in value if ch.isprintable())
    return cleaned[:limit]


def build_upload_params(spec: UploadSpec) -> dict[str, str]:
    """All values are strings, exactly as they will be POSTed, so the signature matches."""
    public_id = str(spec.asset_id)
    tags = [
        "evidentia",
        f"org_{spec.organization_id}",
        f"proj_{spec.project_id}",
        f"site_{spec.site_id}" if spec.site_id else "site_unassigned",
        *spec.extra_tags,
    ]
    if spec.declared_activity:
        tags.append(f"declared_{spec.declared_activity}")

    context: dict[str, str] = {
        "ev_asset_id": public_id,
        "ev_org_id": str(spec.organization_id),
        "ev_project_id": str(spec.project_id),
        "ev_uploaded_by": str(spec.uploaded_by),
    }
    if spec.site_id:
        context["ev_site_id"] = str(spec.site_id)
    if spec.original_filename:
        context["original_filename"] = _sanitize_context_value(spec.original_filename)
    if spec.declared_activity:
        context["declared_activity"] = spec.declared_activity
    if spec.contributor_note:
        context["contributor_note"] = _sanitize_context_value(spec.contributor_note, 1000)

    params: dict[str, str] = {
        "public_id": public_id,
        "asset_folder": asset_folder(spec),
        "type": "authenticated",  # never publicly deliverable without a signature
        "overwrite": "false",  # evidence is immutable
        "tags": ",".join(tags),
        "context": cloudinary.utils.encode_context(context),
        "media_metadata": "true",
        "eager": eager_param(spec.resource_type, named=spec.use_named_transformations),
        "eager_async": "true",
    }
    if spec.resource_type == "image":
        params["phash"] = "true"
    if spec.notification_url:
        params["notification_url"] = spec.notification_url
        params["eager_notification_url"] = spec.notification_url
    if spec.upload_preset:
        params["upload_preset"] = spec.upload_preset
    if spec.use_structured_metadata:
        metadata = {
            "ev_project_id": str(spec.project_id),
            "ev_site_id": str(spec.site_id) if spec.site_id else "",
            "ev_verification_status": "unreviewed",
        }
        if spec.declared_activity:
            metadata["ev_activity"] = spec.declared_activity
        params["metadata"] = "|".join(f"{k}={v}" for k, v in metadata.items() if v)
    return params


def sign_params(
    params: dict[str, str], creds: CloudinaryCredentials, *, timestamp: int | None = None
) -> dict[str, str]:
    to_sign = {k: v for k, v in params.items() if k not in _UNSIGNED and v != ""}
    to_sign["timestamp"] = str(timestamp or int(time.time()))
    signature = cloudinary.utils.api_sign_request(
        to_sign, creds.api_secret, algorithm=creds.signature_algorithm
    )
    return {**to_sign, "api_key": creds.api_key, "signature": signature}


def create_signed_upload(spec: UploadSpec, creds: CloudinaryCredentials) -> SignedUpload:
    fields = sign_params(build_upload_params(spec), creds)
    return SignedUpload(
        upload_url=UPLOAD_ENDPOINT.format(cloud=creds.cloud_name, resource_type=spec.resource_type),
        fields=fields,
        public_id=fields["public_id"],
        expires_at=int(fields["timestamp"]) + 3600,
    )


def verify_upload_response(
    public_id: str, version: int | str, signature: str, creds: CloudinaryCredentials
) -> bool:
    """Verify the `signature` Cloudinary returns in the upload response.

    It signs {public_id, version} with our API secret, so a browser cannot fake a successful upload
    confirmation for an asset that was never stored.
    """
    expected = cloudinary.utils.api_sign_request(
        {"public_id": public_id, "version": str(version)},
        creds.api_secret,
        algorithm=creds.signature_algorithm,
    )
    return hmac.compare_digest(expected.encode(), signature.encode())


def report_pdf_path(
    folder_root: str,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    version: int,
) -> tuple[str, str]:
    """(asset_folder, public_id) for a published report version's PDF."""
    folder = f"{folder_root}/org_{organization_id}/proj_{project_id}/reports"
    return folder, f"{folder}/report_{report_id}_v{version}.pdf"
