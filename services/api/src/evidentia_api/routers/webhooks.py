from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from evidentia_api.deps import CloudinaryDep, SettingsDep
from evidentia_api.services.webhooks import handle_notification

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("/cloudinary")
async def cloudinary_webhook(
    request: Request, settings: SettingsDep, creds: CloudinaryDep
) -> dict[str, Any]:
    """Cloudinary notifications. Authenticated by signature (no bearer token).

    The raw body is verified byte-for-byte before it is parsed.
    """
    body = await request.body()
    return await handle_notification(body, request.headers, settings, creds)
