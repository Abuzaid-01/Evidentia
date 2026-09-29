"""Public external share endpoint (unauthenticated)."""

from __future__ import annotations

from evidentia_core.db.session import system_session
from fastapi import APIRouter

from evidentia_api.deps import SettingsDep
from evidentia_api.schemas.campaigns import SharedContentOut
from evidentia_api.services import campaigns as svc

router = APIRouter(prefix="/v1", tags=["share"])


@router.get(
    "/share/{token}",
    response_model=SharedContentOut,
)
async def get_shared_content(
    token: str,
    settings: SettingsDep,
) -> SharedContentOut:
    """Public resolver for external share links.

    No bearer token required. Always delivers face-redacted media and coarsened GPS.
    """
    async with system_session() as session:
        result = await svc.resolve_shared_content(session, token, settings)
        await session.commit()
        return result
