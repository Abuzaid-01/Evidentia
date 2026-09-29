"""Cloudinary webhook inbox: verify -> store raw -> deduplicate -> act.

Runs in a system (RLS-bypass) session because a webhook carries no user; every query is scoped
explicitly by the asset we resolve from the payload.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import structlog
from evidentia_cloudinary import CloudinaryCredentials
from evidentia_cloudinary.transformations import ALL as NAMED_TRANSFORMATIONS
from evidentia_cloudinary.webhooks import idempotency_key, parse_payload, verify_notification
from evidentia_core.config import Settings
from evidentia_core.db.models import Asset, Derivative, WebhookEvent
from evidentia_core.db.session import system_session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.errors import AppError, Unauthorized
from evidentia_api.services.ingestion import claim_upload, enqueue_pipeline

log = structlog.get_logger("evidentia.webhooks")

_BY_DEFINITION = {nt.definition: nt for nt in NAMED_TRANSFORMATIONS}
_BY_NAME = {f"t_{nt.name}": nt for nt in NAMED_TRANSFORMATIONS}


async def handle_notification(
    body: bytes,
    headers: Mapping[str, str],
    settings: Settings,
    creds: CloudinaryCredentials,
) -> dict[str, Any]:
    verification = verify_notification(
        body,
        headers,
        creds.api_secret,
        algorithm=creds.signature_algorithm,
        max_age_seconds=settings.cloudinary_webhook_max_age_seconds,
    )
    if not verification.valid:
        log.warning("webhook_rejected", reason=verification.reason, scheme=verification.scheme)
        raise Unauthorized(f"Webhook rejected: {verification.reason}")

    try:
        payload = parse_payload(body)
    except ValueError as exc:
        raise AppError("Webhook body is not a JSON object", code="bad_payload") from exc

    key = idempotency_key(payload, body)
    async with system_session() as session:
        event_id = await session.scalar(
            insert(WebhookEvent)
            .values(
                idempotency_key=key,
                notification_type=payload.get("notification_type"),
                public_id=payload.get("public_id"),
                signature_scheme=verification.scheme,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=[WebhookEvent.idempotency_key])
            .returning(WebhookEvent.id)
        )
        if event_id is None:
            await session.commit()
            return {"status": "duplicate", "key": key}

        event = await session.get(WebhookEvent, event_id)
        assert event is not None
        outcome, enqueue_id = await _dispatch(session, event, payload)
        event.outcome = outcome
        event.processed_at = datetime.now(UTC)
        await session.commit()

    if enqueue_id is not None:
        enqueue_pipeline(enqueue_id)
    log.info("webhook_processed", type=payload.get("notification_type"), outcome=outcome)
    return {"status": "processed", "outcome": outcome}


async def _find_asset(session: AsyncSession, payload: Mapping[str, Any]) -> Asset | None:
    public_id = payload.get("public_id")
    if not public_id:
        return None
    return await session.scalar(select(Asset).where(Asset.public_id == str(public_id)))


async def _dispatch(
    session: AsyncSession, event: WebhookEvent, payload: dict[str, Any]
) -> tuple[str, Any]:
    notification_type = payload.get("notification_type")
    asset = await _find_asset(session, payload)
    if asset is not None:
        event.asset_id = asset.id
        event.organization_id = asset.organization_id

    if notification_type == "upload":
        if asset is None:
            return "unknown_asset", None
        version = payload.get("version")
        claimed = await claim_upload(
            session, asset, version=int(version) if version else None, source="webhook"
        )
        return ("claimed", asset.id) if claimed else ("already_claimed", None)

    if notification_type == "eager":
        if asset is None:
            return "unknown_asset", None
        recorded = _record_eager(session, asset, payload.get("eager") or [])
        return f"derivatives_recorded:{recorded}", None

    return "ignored", None


def _record_eager(session: AsyncSession, asset: Asset, eager: list[dict[str, Any]]) -> int:
    count = 0
    for item in eager:
        transformation = str(item.get("transformation", ""))
        # Cloudinary reports the transformation string it executed; map back to our named ones.
        head = transformation.split("/")[0]
        named = _BY_NAME.get(head) or _BY_DEFINITION.get(transformation)
        session.add(
            Derivative(
                organization_id=asset.organization_id,
                asset_id=asset.id,
                purpose=_purpose_for(named.name) if named else "eager",
                named_transformation=named.name if named else None,
                transformation=transformation,
                format=item.get("format"),
                source="eager",
                bytes=item.get("bytes"),
            )
        )
        count += 1
    return count


def _purpose_for(name: str) -> str:
    for purpose in ("thumb", "review", "public", "poster", "ai"):
        if purpose in name:
            return "thumb" if purpose == "poster" else purpose
    return "eager"
