"""Execute one analysis as an idempotent, fully-recorded AnalysisRun.

* run_key = hash(asset, generation, task, provider, prompt version, taxonomy version, extra)
* a SUCCEEDED run with the same key is never repeated (safe worker retries, no duplicate outputs)
* the run row and its observations are committed in one transaction
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from evidentia_ai.normalize import ObservationDraft
from evidentia_core.db.models import AnalysisRun, Asset, Observation
from evidentia_core.domain.enums import AnalysisTask, RunStatus, SourceKind
from sqlalchemy import select
from sqlalchemy.orm import Session

from evidentia_worker.errors import TRANSIENT_EXCEPTIONS


@dataclass
class RunOutput:
    drafts: list[ObservationDraft]
    raw: dict[str, Any]
    latency_ms: int = 0
    model: str | None = None
    provider: str | None = None  # actual provider when the spec is a chain
    model_version: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    payload: Any = None  # typed result for the caller (e.g. the VisionExtraction)


@dataclass
class RunSpec:
    task: AnalysisTask
    provider: str
    model: str
    prompt_version: str | None = None
    prompt_hash: str | None = None
    schema_version: str | None = None
    taxonomy_version: int | None = None
    extra_key: str = ""
    input: dict[str, Any] | None = None


def run_key(asset: Asset, spec: RunSpec) -> str:
    parts = [
        str(asset.id),
        str(asset.analysis_generation),
        spec.task.value,
        spec.provider,
        spec.prompt_version or "",
        str(spec.taxonomy_version or ""),
        spec.extra_key,
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


class PermanentRunFailure(Exception):
    """This analysis cannot succeed (add-on disabled, invalid output...). Recorded, then skipped."""


def execute(
    session: Session, asset: Asset, spec: RunSpec, fn: Callable[[], RunOutput]
) -> tuple[AnalysisRun, RunOutput | None]:
    key = run_key(asset, spec)
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.run_key == key))
    if run is not None and run.status == RunStatus.SUCCEEDED:
        return run, None  # already done in an earlier attempt

    if run is None:
        run = AnalysisRun(
            organization_id=asset.organization_id,
            asset_id=asset.id,
            task=spec.task,
            provider=spec.provider,
            model=spec.model,
            prompt_version=spec.prompt_version,
            prompt_hash=spec.prompt_hash,
            schema_version=spec.schema_version,
            taxonomy_version=spec.taxonomy_version,
            generation=asset.analysis_generation,
            run_key=key,
            input=spec.input,
        )
        session.add(run)
    run.status = RunStatus.RUNNING
    run.attempts = (run.attempts or 0) + 1
    run.error = None
    session.flush()

    try:
        output = fn()
    except TRANSIENT_EXCEPTIONS as exc:
        _fail(session, run, f"transient: {exc}")
        raise
    except PermanentRunFailure as exc:
        _fail(session, run, str(exc))
        return run, None

    run.status = RunStatus.SUCCEEDED
    run.raw_output = output.raw
    run.latency_ms = output.latency_ms
    run.usage = output.usage or None
    run.model = output.model or run.model
    run.provider = output.provider or run.provider
    run.model_version = output.model_version
    run.finished_at = datetime.now(UTC)
    for draft in output.drafts:
        session.add(
            Observation(
                organization_id=asset.organization_id,
                asset_id=asset.id,
                analysis_run_id=run.id,
                generation=asset.analysis_generation,
                ontology_type=draft.ontology_type,
                subject=draft.subject,
                predicate=draft.predicate,
                value=draft.value or None,
                confidence=draft.confidence,
                evidence_span=draft.evidence_span,
                source_kind=SourceKind.AI,
                source_provider=output.provider or spec.provider,
            )
        )
    session.commit()
    return run, output


def _fail(session: Session, run: AnalysisRun, error: str) -> None:
    run.status = RunStatus.FAILED
    run.error = error[:2000]
    run.finished_at = datetime.now(UTC)
    session.commit()
