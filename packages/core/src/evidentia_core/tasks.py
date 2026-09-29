"""Task names and queues shared by the API (producer) and workers (consumer).

The API never imports worker code; it sends tasks by name through this thin Celery client.
"""

from __future__ import annotations

from functools import lru_cache

from celery import Celery

from evidentia_core.config import get_settings

PROCESS_ASSET = "evidentia.pipeline.process_asset"
REANALYZE_ASSET = "evidentia.pipeline.reanalyze_asset"
EXPIRE_STALE_UPLOADS = "evidentia.maintenance.expire_stale_uploads"
REINDEX_ASSET = "evidentia.search.reindex_asset"
REINDEX_PROJECT = "evidentia.search.reindex_project"
SYNC_REVIEW_TO_CLOUDINARY = "evidentia.cloudinary.sync_review"
RENDER_REPORT_PDF = "evidentia.reports.render_pdf"
INGEST_SPEECH = "evidentia.pipeline.ingest_speech"
ANALYZE_PAIR = "evidentia.before_after.analyze_pair"

QUEUE_INGEST = "ingest"
QUEUE_ANALYSIS = "analysis"
QUEUE_MAINTENANCE = "maintenance"
QUEUE_REPORTS = "reports"
QUEUE_ML = "ml"  # CPU-heavy self-hosted vision (before/after alignment, change detection)

TASK_ROUTES = {
    PROCESS_ASSET: {"queue": QUEUE_INGEST},
    REANALYZE_ASSET: {"queue": QUEUE_ANALYSIS},
    EXPIRE_STALE_UPLOADS: {"queue": QUEUE_MAINTENANCE},
    REINDEX_ASSET: {"queue": QUEUE_ANALYSIS},
    REINDEX_PROJECT: {"queue": QUEUE_MAINTENANCE},
    SYNC_REVIEW_TO_CLOUDINARY: {"queue": QUEUE_MAINTENANCE},
    RENDER_REPORT_PDF: {"queue": QUEUE_REPORTS},
    INGEST_SPEECH: {"queue": QUEUE_ANALYSIS},
    ANALYZE_PAIR: {"queue": QUEUE_ML},
}


@lru_cache
def producer() -> Celery:
    app = Celery("evidentia-producer", broker=get_settings().redis_url)
    app.conf.task_routes = TASK_ROUTES
    return app


def enqueue(task_name: str, *args: str) -> str:
    result = producer().send_task(task_name, args=list(args))
    return str(result.id)
