from __future__ import annotations

from evidentia_core.db.models import Organization, User
from evidentia_core.db.session import system_session
from fastapi import APIRouter, Request

from evidentia_api.deps import CurrentPrincipal, SettingsDep
from evidentia_api.errors import NotFound
from evidentia_api.schemas.identity import MeOut, OrganizationOut, UserOut

router = APIRouter(prefix="/v1", tags=["identity"])


@router.get("/me", response_model=MeOut)
async def me(principal: CurrentPrincipal, request: Request, settings: SettingsDep) -> MeOut:
    async with system_session() as session:
        user = await session.get(User, principal.user_id)
        org = await session.get(Organization, principal.org_id)
    if user is None or org is None:
        raise NotFound("Identity not found")
    creds = request.app.state.cloudinary
    return MeOut(
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(org),
        role=principal.role,
        auth_mode=settings.auth_mode,
        cloudinary_cloud_name=creds.cloud_name if creds else None,
        features={
            "cloudinary": creds is not None,
            "webhooks": settings.webhook_url is not None,
            "analyze_api": settings.cloudinary_analyze_enabled,
            "ocr": settings.cloudinary_ocr_enabled,
            "gemini": settings.gemini_api_key is not None,
            "groq": settings.groq_api_key is not None,
            "demo_mode": settings.demo_mode_enabled,
        },
    )
