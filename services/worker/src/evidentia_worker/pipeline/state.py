"""State transitions with persistence + realtime events, in one place."""

from __future__ import annotations

from datetime import UTC, datetime

from evidentia_core.db.models import Asset
from evidentia_core.domain.enums import AssetState
from evidentia_core.domain.state_machine import assert_transition
from evidentia_core.events import build_event
from sqlalchemy.orm import Session

from evidentia_worker.context import WorkerContext


def transition(
    session: Session,
    asset: Asset,
    target: AssetState,
    ctx: WorkerContext,
    *,
    reason: str | None = None,
    commit: bool = True,
) -> None:
    assert_transition(asset.state, target)
    asset.state = target
    asset.state_reason = reason
    asset.state_changed_at = datetime.now(UTC)
    if commit:
        session.commit()
        publish_state(asset, ctx)


def publish_state(asset: Asset, ctx: WorkerContext) -> None:
    ctx.publisher.publish(
        asset.organization_id,
        build_event(
            "asset.state_changed",
            asset_id=asset.id,
            project_id=asset.project_id,
            state=asset.state.value,
            reason=asset.state_reason,
            caption=asset.caption,
            top_activity=asset.top_activity,
        ),
    )
