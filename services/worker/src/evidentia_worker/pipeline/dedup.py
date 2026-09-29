"""METADATA_READY -> DEDUP_CHECKED: exact (SHA-256) and perceptual (pHash) duplicates.

Duplicates are review signals only. Evidence is never deleted automatically.
"""

from __future__ import annotations

from evidentia_core.db.models import Asset
from evidentia_core.domain.enums import AssetState, ResourceType
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from evidentia_worker.context import WorkerContext
from evidentia_worker.pipeline.state import transition

_EXCLUDED = (AssetState.AWAITING_UPLOAD.value, AssetState.EXPIRED.value)

_NEAR_SQL = text(
    """
    SELECT id, bit_count(((phash # :phash))::bit(64)) AS distance
    FROM assets
    WHERE project_id = :project_id
      AND id <> :asset_id
      AND phash IS NOT NULL
      AND state NOT IN :excluded
    ORDER BY distance
    LIMIT 5
    """
).bindparams(bindparam("excluded", expanding=True))


def check_duplicates(session: Session, asset: Asset, ctx: WorkerContext) -> None:
    asset.exact_duplicate_of_id = None
    if asset.sha256:
        asset.exact_duplicate_of_id = session.scalar(
            select(Asset.id)
            .where(
                Asset.organization_id == asset.organization_id,
                Asset.sha256 == asset.sha256,
                Asset.id != asset.id,
                Asset.state.notin_([AssetState.AWAITING_UPLOAD, AssetState.EXPIRED]),
            )
            .order_by(Asset.created_at)
            .limit(1)
        )

    near: list[dict[str, object]] = []
    if asset.resource_type == ResourceType.IMAGE and asset.phash is not None:
        rows = session.execute(
            _NEAR_SQL,
            {
                "phash": asset.phash,
                "project_id": asset.project_id,
                "asset_id": asset.id,
                "excluded": _EXCLUDED,
            },
        )
        max_distance = ctx.settings.near_duplicate_max_distance
        near = [
            {"asset_id": str(row.id), "distance": int(row.distance)}
            for row in rows
            if row.distance <= max_distance and row.id != asset.exact_duplicate_of_id
        ]
    asset.near_duplicates = near or None
    transition(session, asset, AssetState.DEDUP_CHECKED, ctx)
