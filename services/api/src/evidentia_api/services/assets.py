"""Asset queries and presentation (signed thumbnails, detail assembly)."""

from __future__ import annotations

import uuid
from typing import Any

from evidentia_cloudinary.delivery import (
    DeliveryUrl,
    clip_url,
    original_download_url,
    rendition_url,
    stream_url,
)
from evidentia_core.config import Settings
from evidentia_core.db.models import AnalysisRun, Asset, Derivative, Observation
from evidentia_core.domain.enums import AssetState, ObservationStatus, ResourceType
from evidentia_core.domain.video import chapter_cues, chapters_vtt
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from evidentia_api.errors import NotFound, Unprocessable
from evidentia_api.schemas.assets import (
    AnalysisRunOut,
    AssetDetail,
    AssetSummary,
    CloudinaryRef,
    DerivativeOut,
    NearDuplicate,
    ObservationOut,
)
from evidentia_api.schemas.common import decode_cursor, encode_cursor

_HAS_MEDIA = frozenset(set(AssetState) - {AssetState.AWAITING_UPLOAD, AssetState.EXPIRED})


async def get_asset(session: AsyncSession, asset_id: uuid.UUID) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise NotFound("Asset not found")
    return asset


def thumb_url(asset: Asset, settings: Settings, *, cloudinary_ready: bool) -> str | None:
    if not cloudinary_ready or asset.state not in _HAS_MEDIA:
        return None
    return rendition_url(
        asset.public_id,
        asset.resource_type.value,
        "thumb",
        use_named=settings.cloudinary_use_named_transformations,
    ).url


def to_summary(asset: Asset, settings: Settings, *, cloudinary_ready: bool) -> AssetSummary:
    summary = AssetSummary.model_validate(asset)
    summary.thumb_url = thumb_url(asset, settings, cloudinary_ready=cloudinary_ready)
    return summary


async def list_assets(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    state: AssetState | None,
    site_id: uuid.UUID | None,
    resource_type: ResourceType | None,
    include_pending: bool,
    cursor: str | None,
    limit: int,
) -> tuple[list[Asset], str | None]:
    query = select(Asset).where(Asset.project_id == project_id)
    if state:
        query = query.where(Asset.state == state)
    elif not include_pending:
        query = query.where(Asset.state.notin_([AssetState.AWAITING_UPLOAD, AssetState.EXPIRED]))
    if site_id:
        query = query.where(Asset.site_id == site_id)
    if resource_type:
        query = query.where(Asset.resource_type == resource_type)
    if cursor:
        created_at, last_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Asset.created_at < created_at,
                and_(Asset.created_at == created_at, Asset.id < last_id),
            )
        )
    rows = list(
        (
            await session.scalars(
                query.order_by(Asset.created_at.desc(), Asset.id.desc()).limit(limit + 1)
            )
        ).all()
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
    return rows, next_cursor


def _phash_hex(value: int | None) -> str | None:
    if value is None:
        return None
    return f"{value & ((1 << 64) - 1):016x}"


async def asset_detail(
    session: AsyncSession, asset: Asset, settings: Settings, *, cloudinary_ready: bool
) -> AssetDetail:
    observations = (
        await session.scalars(
            select(Observation)
            .where(
                Observation.asset_id == asset.id, Observation.status != ObservationStatus.SUPERSEDED
            )
            .order_by(Observation.ontology_type, Observation.confidence.desc().nulls_last())
        )
    ).all()
    runs = (
        await session.scalars(
            select(AnalysisRun)
            .where(AnalysisRun.asset_id == asset.id)
            .order_by(AnalysisRun.created_at.desc())
        )
    ).all()
    derivatives = (
        await session.scalars(
            select(Derivative)
            .where(Derivative.asset_id == asset.id)
            .order_by(Derivative.created_at)
        )
    ).all()

    base: dict[str, Any] = AssetSummary.model_validate(asset).model_dump()
    base["thumb_url"] = thumb_url(asset, settings, cloudinary_ready=cloudinary_ready)
    return AssetDetail(
        **base,
        uploaded_by_id=asset.uploaded_by_id,
        contributor_note=asset.contributor_note,
        declared_capture_time=asset.declared_capture_time,
        latitude=asset.latitude,
        longitude=asset.longitude,
        exif=asset.exif,
        sha256=asset.sha256,
        phash_hex=_phash_hex(asset.phash),
        quality_score=asset.quality_score,
        review_reasons=asset.review_reasons,
        near_duplicates=[NearDuplicate.model_validate(d) for d in asset.near_duplicates or []],
        cloudinary=CloudinaryRef(
            public_id=asset.public_id,
            asset_id=asset.cloudinary_asset_id,
            version=asset.cloudinary_version,
            asset_folder=asset.asset_folder,
            delivery_type=asset.delivery_type,
        ),
        observations=[ObservationOut.model_validate(o) for o in observations],
        analysis_runs=[AnalysisRunOut.model_validate(r) for r in runs],
        derivatives=[DerivativeOut.model_validate(d) for d in derivatives],
        analysis_generation=asset.analysis_generation,
        uploaded_at=asset.uploaded_at,
        state_changed_at=asset.state_changed_at,
    )


def media_url(
    asset: Asset,
    variant: str,
    settings: Settings,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> DeliveryUrl:
    if asset.state not in _HAS_MEDIA:
        raise Unprocessable("This asset has no stored media yet")
    if variant == "original":
        if not asset.format:
            raise Unprocessable("Original format unknown until the asset is registered")
        return original_download_url(asset.public_id, asset.resource_type.value, asset.format)
    if variant in {"stream", "clip"} and asset.resource_type != ResourceType.VIDEO:
        raise Unprocessable(f"'{variant}' is only available for video")
    if variant == "stream":
        return stream_url(asset.public_id, version=asset.cloudinary_version)
    if variant == "clip":
        if start_ms is None or end_ms is None:
            raise Unprocessable("A clip needs start_ms and end_ms")
        if end_ms <= start_ms:
            raise Unprocessable("end_ms must be after start_ms")
        if asset.duration_seconds and end_ms > int(asset.duration_seconds * 1000) + 1000:
            raise Unprocessable("The clip extends past the end of the video")
        return clip_url(asset.public_id, start_ms, end_ms, version=asset.cloudinary_version)
    return rendition_url(
        asset.public_id,
        asset.resource_type.value,
        variant,
        use_named=settings.cloudinary_use_named_transformations,
    )


def chapters_for(observations: list[Observation]) -> str:
    cues = chapter_cues(
        [
            (o.ontology_type.value, o.subject, o.value, o.evidence_span)
            for o in observations
            if o.status != ObservationStatus.SUPERSEDED
        ]
    )
    return chapters_vtt(cues)


async def record_clip(session: AsyncSession, asset: Asset, delivery: DeliveryUrl) -> None:
    """Remember the exact so_/eo_ string the first time a span is cut, for lineage."""
    if delivery.variant != "clip":
        return
    already = await session.scalar(
        select(Derivative.id).where(
            Derivative.asset_id == asset.id,
            Derivative.purpose == "clip",
            Derivative.transformation == delivery.transformation,
        )
    )
    if already is not None:
        return
    session.add(
        Derivative(
            organization_id=asset.organization_id,
            asset_id=asset.id,
            purpose="clip",
            transformation=delivery.transformation,
            format="mp4",
            source="on_demand",
            bytes=None,
        )
    )
    await session.commit()
