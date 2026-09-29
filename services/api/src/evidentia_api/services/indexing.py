"""API-side refresh of an asset's search document after human decisions (same builder as the worker;
the text embedding is then refreshed asynchronously by the worker)."""

from __future__ import annotations

from evidentia_core.db.models import Asset, Observation, Project, Site, Taxonomy
from evidentia_core.domain.enums import ObservationStatus, OntologyType
from evidentia_core.domain.search_doc import ObservationText, build_search_text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def refresh_search_document(db: AsyncSession, asset: Asset) -> None:
    observations = (
        await db.scalars(
            select(Observation).where(
                Observation.asset_id == asset.id,
                Observation.status.in_([ObservationStatus.PROPOSED, ObservationStatus.VERIFIED]),
            )
        )
    ).all()
    project = await db.get(Project, asset.project_id)
    taxonomy = await db.scalar(
        select(Taxonomy).where(
            Taxonomy.project_id == asset.project_id,
            Taxonomy.version == (project.active_taxonomy_version if project else 1),
        )
    )
    site = await db.get(Site, asset.site_id) if asset.site_id else None
    asset.search_text = build_search_text(
        caption=asset.caption,
        observations=[
            ObservationText(
                o.ontology_type.value, o.subject, o.predicate, o.status.value, o.value, o.confidence
            )
            for o in observations
        ],
        activity_labels={a["key"]: a["label"] for a in (taxonomy.activities if taxonomy else [])},
        site_name=site.name if site else None,
        filename=asset.original_filename,
        note=asset.contributor_note,
    )
    asset.verified_activities = (
        sorted(
            {
                o.subject
                for o in observations
                if o.ontology_type == OntologyType.ACTIVITY
                and o.status == ObservationStatus.VERIFIED
                and o.subject != "other"
            }
        )
        or None
    )
