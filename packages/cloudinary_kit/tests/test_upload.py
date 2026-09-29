import uuid

import cloudinary.utils
from evidentia_cloudinary import CloudinaryCredentials
from evidentia_cloudinary.upload import (
    UploadSpec,
    build_upload_params,
    create_signed_upload,
    verify_upload_response,
)

CREDS = CloudinaryCredentials("demo-cloud", "1234", "s3cr3t")
ORG, PROJECT, SITE, USER, ASSET = (uuid.uuid4() for _ in range(5))


def _spec(**overrides: object) -> UploadSpec:
    values: dict[str, object] = {
        "asset_id": ASSET,
        "organization_id": ORG,
        "project_id": PROJECT,
        "site_id": SITE,
        "resource_type": "image",
        "uploaded_by": USER,
        "folder_root": "evidentia",
        "original_filename": "IMG_0001.JPG",
        "declared_activity": "pipe_installation",
        "notification_url": "https://api.example.org/v1/webhooks/cloudinary",
    }
    values.update(overrides)
    return UploadSpec(**values)  # type: ignore[arg-type]


def test_server_controls_identity_folder_and_privacy() -> None:
    params = build_upload_params(_spec())
    assert params["public_id"] == str(ASSET)
    assert params["type"] == "authenticated"
    assert params["overwrite"] == "false"
    assert params["asset_folder"] == f"evidentia/org_{ORG}/proj_{PROJECT}/site_{SITE}"
    assert params["phash"] == "true"
    assert params["eager"] == "t_ev_thumb|t_ev_review"
    assert params["notification_url"].endswith("/v1/webhooks/cloudinary")
    assert f"proj_{PROJECT}" in params["tags"]
    assert "declared_pipe_installation" in params["tags"]


def test_video_uses_poster_eager_and_no_phash() -> None:
    params = build_upload_params(_spec(resource_type="video"))
    assert "phash" not in params
    assert params["eager"] == "t_ev_video_poster/jpg"


def test_inline_transformations_when_named_disabled() -> None:
    params = build_upload_params(_spec(use_named_transformations=False))
    assert params["eager"].startswith("c_fill,g_auto")


def test_context_is_escaped() -> None:
    params = build_upload_params(_spec(contributor_note="a=b|c"))
    assert "contributor_note=a\\=b\\|c" in params["context"]


def test_structured_metadata_only_when_enabled() -> None:
    assert "metadata" not in build_upload_params(_spec())
    params = build_upload_params(_spec(use_structured_metadata=True))
    assert f"ev_project_id={PROJECT}" in params["metadata"]


def test_signature_covers_every_parameter() -> None:
    signed = create_signed_upload(_spec(), CREDS)
    fields = dict(signed.fields)
    signature = fields.pop("signature")
    fields.pop("api_key")
    assert cloudinary.utils.api_sign_request(fields, CREDS.api_secret) == signature
    # Any client-side change (e.g. making it public) no longer matches the signature.
    fields["type"] = "upload"
    assert cloudinary.utils.api_sign_request(fields, CREDS.api_secret) != signature
    assert signed.upload_url == "https://api.cloudinary.com/v1_1/demo-cloud/image/upload"


def test_upload_response_signature() -> None:
    good = cloudinary.utils.api_sign_request({"public_id": "abc", "version": "7"}, "s3cr3t")
    assert verify_upload_response("abc", 7, good, CREDS)
    assert not verify_upload_response("abc", 8, good, CREDS)
    assert not verify_upload_response("abd", 7, good, CREDS)
