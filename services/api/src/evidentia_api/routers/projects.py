from __future__ import annotations

import uuid

from evidentia_core.db.models import Project, Site, Taxonomy
from evidentia_core.domain.taxonomy import PRESETS, TaxonomySpec
from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select

from evidentia_api.deps import CloudinaryDep, Manager, RequestId, SettingsDep, TenantDB, Viewer
from evidentia_api.errors import Unprocessable
from evidentia_api.schemas.analytics import ProjectAnalyticsOut
from evidentia_api.schemas.projects import (
    ProjectCreate,
    ProjectDeleteOut,
    ProjectOut,
    ProjectUpdate,
    SiteCreate,
    SiteOut,
    SiteUpdate,
    TaxonomyOut,
    TaxonomyPresetOut,
    TaxonomyUpdate,
)
from evidentia_api.schemas.spatial import SpatialTemporalOut
from evidentia_api.services import analytics as analytics_svc
from evidentia_api.services import audit, project_deletion
from evidentia_api.services import projects as svc
from evidentia_api.services import spatial as spatial_svc

router = APIRouter(prefix="/v1", tags=["projects"])


@router.get("/taxonomy-presets", response_model=list[TaxonomyPresetOut])
async def taxonomy_presets(_: Viewer) -> list[TaxonomyPresetOut]:
    return [
        TaxonomyPresetOut(name=name, activities=spec.activities) for name, spec in PRESETS.items()
    ]


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(_: Viewer, db: TenantDB) -> list[ProjectOut]:
    projects = (await db.scalars(select(Project).order_by(Project.created_at.desc()))).all()
    stats = await svc.project_stats(db, [p.id for p in projects])
    out = []
    for project in projects:
        item = ProjectOut.model_validate(project)
        item.stats = stats[project.id]
        out.append(item)
    return out


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, principal: Manager, db: TenantDB, rid: RequestId
) -> ProjectOut:
    project = await svc.create_project(db, principal, body, rid)
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, _: Viewer, db: TenantDB) -> ProjectOut:
    project = await svc.get_project(db, project_id)
    item = ProjectOut.model_validate(project)
    item.stats = (await svc.project_stats(db, [project.id]))[project.id]
    return item


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, principal: Manager, db: TenantDB, rid: RequestId
) -> ProjectOut:
    project = await svc.get_project(db, project_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(project, field, value)
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="project.updated",
        target_type="project",
        target_id=project.id,
        data={k: str(v) for k, v in changes.items()},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(project)
    return ProjectOut.model_validate(project)


@router.delete("/projects/{project_id}", response_model=ProjectDeleteOut)
async def delete_project(
    project_id: uuid.UUID,
    principal: Manager,
    db: TenantDB,
    request: Request,
    rid: RequestId,
    confirm_name: str = Query(
        min_length=1, description="The project's exact name, as confirmation"
    ),
) -> ProjectDeleteOut:
    """Permanently delete the project and everything in it (photos, claims, reports), then remove
    its files from Cloudinary in the background. Audited; cannot be undone."""
    return await project_deletion.delete_project(
        db,
        principal,
        project_id,
        confirm_name,
        cloudinary_ready=request.app.state.cloudinary is not None,
        rid=rid,
    )


@router.get("/projects/{project_id}/spatial-temporal", response_model=SpatialTemporalOut)
async def get_project_spatial_temporal(
    project_id: uuid.UUID,
    _: Viewer,
    db: TenantDB,
    settings: SettingsDep,
    creds: CloudinaryDep,
) -> SpatialTemporalOut:
    await svc.get_project(db, project_id)
    return await spatial_svc.get_spatial_temporal(
        db,
        project_id,
        settings,
        cloudinary_ready=creds is not None,
    )


@router.get("/projects/{project_id}/analytics", response_model=ProjectAnalyticsOut)
async def get_project_analytics_endpoint(
    project_id: uuid.UUID,
    _: Viewer,
    db: TenantDB,
) -> ProjectAnalyticsOut:
    await svc.get_project(db, project_id)
    return await analytics_svc.get_project_analytics(db, project_id)


# --- sites ------------------------------------------------------------------------------------


@router.get("/projects/{project_id}/sites", response_model=list[SiteOut])
async def list_sites(project_id: uuid.UUID, _: Viewer, db: TenantDB) -> list[SiteOut]:
    await svc.get_project(db, project_id)
    sites = (
        await db.scalars(select(Site).where(Site.project_id == project_id).order_by(Site.code))
    ).all()
    return [SiteOut.model_validate(s) for s in sites]


@router.post(
    "/projects/{project_id}/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED
)
async def create_site(
    project_id: uuid.UUID, body: SiteCreate, principal: Manager, db: TenantDB, rid: RequestId
) -> SiteOut:
    project = await svc.get_project(db, project_id)
    site = await svc.create_site(db, principal, project, body, rid)
    return SiteOut.model_validate(site)


@router.patch("/sites/{site_id}", response_model=SiteOut)
async def update_site(
    site_id: uuid.UUID, body: SiteUpdate, principal: Manager, db: TenantDB, rid: RequestId
) -> SiteOut:
    site = await svc.get_site(db, site_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(site, field, value)
    if (site.latitude is None) != (site.longitude is None):
        raise Unprocessable("latitude and longitude must be set together")
    audit.record(
        db,
        org_id=principal.org_id,
        principal=principal,
        action="site.updated",
        target_type="site",
        target_id=site.id,
        data={k: str(v) for k, v in changes.items()},
        request_id=rid,
    )
    await db.commit()
    await db.refresh(site)
    return SiteOut.model_validate(site)


# --- taxonomy -----------------------------------------------------------------------------------


@router.get("/projects/{project_id}/taxonomy", response_model=TaxonomyOut)
async def get_taxonomy(project_id: uuid.UUID, _: Viewer, db: TenantDB) -> TaxonomyOut:
    project = await svc.get_project(db, project_id)
    taxonomy = await svc.active_taxonomy(db, project)
    return _taxonomy_out(taxonomy)


@router.put("/projects/{project_id}/taxonomy", response_model=TaxonomyOut)
async def replace_taxonomy(
    project_id: uuid.UUID, body: TaxonomyUpdate, principal: Manager, db: TenantDB, rid: RequestId
) -> TaxonomyOut:
    project = await svc.get_project(db, project_id)
    spec = TaxonomySpec(activities=body.activities)
    taxonomy = await svc.replace_taxonomy(db, principal, project, spec, rid)
    return _taxonomy_out(taxonomy)


def _taxonomy_out(taxonomy: Taxonomy) -> TaxonomyOut:
    return TaxonomyOut(
        project_id=taxonomy.project_id,
        version=taxonomy.version,
        activities=taxonomy.activities,  # type: ignore[arg-type]
        created_at=taxonomy.created_at,
    )
