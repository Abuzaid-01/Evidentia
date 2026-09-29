"""Processing bookkeeping: webhook inbox, jobs and AI analysis runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk
from evidentia_core.domain.enums import AnalysisTask, JobState, RunStatus


class WebhookEvent(UUIDPk, Base):
    """Raw inbox of Cloudinary notifications. Stored before processing, deduplicated by key."""

    __tablename__ = "webhook_events"

    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    notification_type: Mapped[str | None] = mapped_column(String(60))
    public_id: Mapped[str | None] = mapped_column(String(255), index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    signature_scheme: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]]
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None]
    outcome: Mapped[str | None] = mapped_column(String(60))
    error: Mapped[str | None] = mapped_column(Text)


class Job(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_target", "target_type", "target_id"),)

    type: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID]
    run_key: Mapped[str] = mapped_column(String(200), unique=True)
    state: Mapped[JobState] = mapped_column(default=JobState.QUEUED)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class AnalysisRun(UUIDPk, TenantScoped, Timestamps, Base):
    """One model/tool execution on one asset. The run_key makes retries idempotent."""

    __tablename__ = "analysis_runs"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    task: Mapped[AnalysisTask]
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(60))
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    schema_version: Mapped[str | None] = mapped_column(String(40))
    taxonomy_version: Mapped[int | None]
    generation: Mapped[int] = mapped_column(default=1)
    run_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[RunStatus] = mapped_column(default=RunStatus.RUNNING)
    input: Mapped[dict[str, Any] | None]
    raw_output: Mapped[dict[str, Any] | None]
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None]
    usage: Mapped[dict[str, Any] | None]
    attempts: Mapped[int] = mapped_column(default=0)
    finished_at: Mapped[datetime | None]
