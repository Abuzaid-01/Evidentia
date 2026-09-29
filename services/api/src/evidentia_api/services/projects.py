from __future__ import annotations

import uuid

from evidentia_core.db.models import Asset, Project, Site, Taxonomy
from evidentia_core.domain.enums import AssetState
from evidentia_core.domain.taxonomy import TaxonomySpec, preset
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.auth.principal import Principal
from evidentia_api.errors import Conflict, NotFound, Unprocessable
from evidentia_api.schemas.projects import ProjectCreate, ProjectStats, SiteCreate
from evidentia_api.services import audit


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)  # RLS hides other tenants' rows
    if project is None:
        raise NotFound("Project not found")
    return project


async def get_site(session: AsyncSession, site_id: uuid.UUID) -> Site:
    site = await session.get(Site, site_id)
    if site is None:
        raise NotFound("Site not found")
    return site


async def active_taxonomy(session: AsyncSession, project: Project) -> Taxonomy:
    taxonomy = await session.scalar(
        select(Taxonomy).where(
            Taxonomy.project_id == project.id,
            Taxonomy.version == project.active_taxonomy_version,
        )
    )
    if taxonomy is None:
        raise NotFound("Project has no active taxonomy")
    return taxonomy


async def create_project(
    session: AsyncSession, principal: Principal, body: ProjectCreate, request_id: str | None
) -> Project:
    try:
        spec = preset(body.taxonomy_preset)
    except ValueError as exc:
        raise Unprocessable(str(exc)) from exc

    project = Project(
        organization_id=principal.org_id,
        name=body.name,
        description=body.description,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        taxonomy_preset=body.taxonomy_preset,
        active_taxonomy_version=1,
        created_by_id=principal.user_id,
    )
    session.add(project)
    await session.flush()
    session.add(
        Taxonomy(
            organization_id=principal.org_id,
            project_id=project.id,
            version=1,
            activities=[a.model_dump() for a in spec.activities],
            created_by_id=principal.user_id,
        )
    )
    audit.record(
        session,
        org_id=principal.org_id,
        principal=principal,
        action="project.created",
        target_type="project",
        target_id=project.id,
        data={"name": project.name, "taxonomy_preset": body.taxonomy_preset},
        request_id=request_id,
    )
    await session.commit()
    await session.refresh(project)
    return project


async def project_stats(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ProjectStats]:
    stats = {pid: ProjectStats() for pid in project_ids}
    if not project_ids:
        return stats
    rows = await session.execute(
        select(Asset.project_id, Asset.state, func.count())
        .where(Asset.project_id.in_(project_ids), Asset.state != AssetState.AWAITING_UPLOAD)
        .group_by(Asset.project_id, Asset.state)
    )
    for project_id, state, count in rows:
        entry = stats[project_id]
        entry.by_state[state.value] = count
        entry.assets_total += count
    site_rows = await session.execute(
        select(Site.project_id, func.count())
        .where(Site.project_id.in_(project_ids))
        .group_by(Site.project_id)
    )
    for project_id, count in site_rows:
        stats[project_id].sites = count
    return stats


async def create_site(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    body: SiteCreate,
    request_id: str | None,
) -> Site:
    exists = await session.scalar(
        select(func.count())
        .select_from(Site)
        .where(Site.project_id == project.id, Site.code == body.code)
    )
    if exists:
        raise Conflict(f"A site with code '{body.code}' already exists in this project")
    site = Site(
        organization_id=principal.org_id,
        project_id=project.id,
        name=body.name,
        code=body.code,
        description=body.description,
        latitude=body.latitude,
        longitude=body.longitude,
        radius_m=body.radius_m,
    )
    session.add(site)
    await session.flush()
    audit.record(
        session,
        org_id=principal.org_id,
        principal=principal,
        action="site.created",
        target_type="site",
        target_id=site.id,
        data={"project_id": str(project.id), "code": site.code},
        request_id=request_id,
    )
    await session.commit()
    await session.refresh(site)
    return site


async def replace_taxonomy(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    spec: TaxonomySpec,
    request_id: str | None,
) -> Taxonomy:
    """Taxonomies are versioned, never edited in place: old observations keep their meaning."""
    next_version = project.active_taxonomy_version + 1
    taxonomy = Taxonomy(
        organization_id=principal.org_id,
        project_id=project.id,
        version=next_version,
        activities=[a.model_dump() for a in spec.activities],
        created_by_id=principal.user_id,
    )
    session.add(taxonomy)
    project.active_taxonomy_version = next_version
    audit.record(
        session,
        org_id=principal.org_id,
        principal=principal,
        action="taxonomy.versioned",
        target_type="project",
        target_id=project.id,
        data={"version": next_version, "activities": spec.keys()},
        request_id=request_id,
    )
    await session.commit()
    await session.refresh(taxonomy)
    return taxonomy
