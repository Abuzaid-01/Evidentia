"""Cloudinary webhook (notification) verification and idempotency keys.

Legacy scheme (sent by triggers with auth_scheme "default" or "legacy_hmac", and by per-upload
`notification_url`): X-Cld-Signature = hex(SHA1|SHA256(raw_body + X-Cld-Timestamp + api_secret)).

Triggers configured with auth_scheme "eddsa_v2" send only X-Cld-Signature_v2 (Ed25519). We reject
those explicitly until the v2 public-key distribution is wired in, rather than accepting unverified
payloads. Keep triggers on auth_scheme "default" (sends both headers).

Always verify the raw request bytes. Never re-serialize parsed JSON before verifying.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from evidentia_cloudinary.config import SignatureAlgorithm


@dataclass(frozen=True)
class WebhookVerification:
    valid: bool
    scheme: str
    reason: str = ""


def compute_legacy_signature(
    body: bytes, timestamp: str, api_secret: str, algorithm: SignatureAlgorithm = "sha1"
) -> str:
    digest = hashlib.sha256 if algorithm == "sha256" else hashlib.sha1
    return digest(body + timestamp.encode() + api_secret.encode()).hexdigest()


def verify_notification(
    body: bytes,
    headers: Mapping[str, str],
    api_secret: str,
    *,
    algorithm: SignatureAlgorithm = "sha1",
    max_age_seconds: int = 7200,
    now: float | None = None,
) -> WebhookVerification:
    lowered = {k.lower(): v for k, v in headers.items()}
    timestamp = lowered.get("x-cld-timestamp")
    signature = lowered.get("x-cld-signature")

    if not timestamp:
        return WebhookVerification(False, "none", "missing X-Cld-Timestamp")
    try:
        ts = int(timestamp)
    except ValueError:
        return WebhookVerification(False, "none", "malformed X-Cld-Timestamp")

    current = time.time() if now is None else now
    if max_age_seconds and abs(current - ts) > max_age_seconds:
        return WebhookVerification(
            False, "legacy", "timestamp outside the allowed window (replay?)"
        )

    if signature:
        expected = compute_legacy_signature(body, timestamp, api_secret, algorithm)
        if hmac.compare_digest(expected, signature.strip().lower()):
            return WebhookVerification(True, "legacy")
        return WebhookVerification(False, "legacy", "signature mismatch")

    if lowered.get("x-cld-signature_v2"):
        return WebhookVerification(
            False,
            "eddsa_v2",
            "eddsa_v2-only notifications are not accepted; set the trigger auth_scheme to 'default'",
        )
    return WebhookVerification(False, "none", "missing signature header")


def parse_payload(body: bytes) -> dict[str, Any]:
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("notification payload must be a JSON object")
    return payload


def idempotency_key(payload: Mapping[str, Any], body: bytes) -> str:
    """Stable key so replays and Cloudinary retries are processed once.

    Upload notifications are keyed by (asset, version); anything else by a hash of the raw body.
    """
    notification_type = str(payload.get("notification_type") or "unknown")
    if notification_type == "upload":
        identity = payload.get("asset_id") or payload.get("public_id")
        version = payload.get("version")
        if identity and version:
            return f"upload:{identity}:{version}"
    return f"{notification_type}:{hashlib.sha256(body).hexdigest()}"
