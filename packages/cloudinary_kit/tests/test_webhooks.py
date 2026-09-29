from evidentia_cloudinary.webhooks import (
    compute_legacy_signature,
    idempotency_key,
    verify_notification,
)

SECRET = "abcd"


def test_matches_cloudinary_documented_example() -> None:
    # Example from Cloudinary's "Verifying notification signatures" documentation.
    body = b"{public_id: 'sample'}"
    assert (
        compute_legacy_signature(body, "1315060510", SECRET)
        == "25f7e91709c858b97d688ce8da799dedb290d9ef"
    )


def _headers(body: bytes, ts: int, secret: str = SECRET) -> dict[str, str]:
    return {
        "X-Cld-Timestamp": str(ts),
        "X-Cld-Signature": compute_legacy_signature(body, str(ts), secret),
    }


def test_valid_signature_accepted() -> None:
    body = b'{"notification_type":"upload"}'
    result = verify_notification(body, _headers(body, 1000), SECRET, now=1000)
    assert result.valid and result.scheme == "legacy"


def test_tampered_body_rejected() -> None:
    body = b'{"notification_type":"upload"}'
    headers = _headers(body, 1000)
    result = verify_notification(b'{"notification_type":"delete"}', headers, SECRET, now=1000)
    assert not result.valid and "mismatch" in result.reason


def test_wrong_secret_rejected() -> None:
    body = b"{}"
    result = verify_notification(body, _headers(body, 1000, "other"), SECRET, now=1000)
    assert not result.valid


def test_replay_outside_window_rejected() -> None:
    body = b"{}"
    result = verify_notification(body, _headers(body, 1000), SECRET, now=1000 + 7201)
    assert not result.valid and "window" in result.reason


def test_missing_headers_rejected() -> None:
    assert not verify_notification(b"{}", {}, SECRET).valid
    assert not verify_notification(b"{}", {"X-Cld-Timestamp": "1"}, SECRET, now=1).valid


def test_eddsa_only_notifications_are_not_silently_accepted() -> None:
    headers = {"X-Cld-Timestamp": "1000", "X-Cld-Signature_v2": "abc"}
    result = verify_notification(b"{}", headers, SECRET, now=1000)
    assert not result.valid and result.scheme == "eddsa_v2"


def test_sha256_accounts() -> None:
    body = b"{}"
    ts = "1000"
    headers = {
        "X-Cld-Timestamp": ts,
        "X-Cld-Signature": compute_legacy_signature(body, ts, SECRET, "sha256"),
    }
    assert verify_notification(body, headers, SECRET, algorithm="sha256", now=1000).valid
    assert not verify_notification(body, headers, SECRET, algorithm="sha1", now=1000).valid


def test_idempotency_keys() -> None:
    upload = {"notification_type": "upload", "asset_id": "a1", "version": 5}
    assert idempotency_key(upload, b"x") == "upload:a1:5"
    assert idempotency_key(upload, b"y") == "upload:a1:5"  # same event, different bytes
    eager = {"notification_type": "eager"}
    assert idempotency_key(eager, b"x") != idempotency_key(eager, b"y")
