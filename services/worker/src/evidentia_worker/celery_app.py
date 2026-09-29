"""Celery application. Start with:

uv run celery -A evidentia_worker.celery_app worker -Q ingest,analysis,maintenance,reports,ml --pool=threads -c 4
uv run celery -A evidentia_worker.celery_app beat
"""

from __future__ import annotations

from celery import Celery, signals
from celery.schedules import crontab
from evidentia_core import tasks
from evidentia_core.config import get_settings
from evidentia_core.logging import configure_logging

settings = get_settings()

app = Celery(
    "evidentia",
    broker=settings.redis_url,
    include=[
        "evidentia_worker.tasks.pipeline",
        "evidentia_worker.tasks.maintenance",
        "evidentia_worker.tasks.search",
        "evidentia_worker.tasks.cloudinary_sync",
        "evidentia_worker.tasks.reports",
        "evidentia_worker.tasks.before_after",
    ],
)
app.conf.update(
    task_routes=tasks.TASK_ROUTES,
    task_default_queue=tasks.QUEUE_INGEST,
    task_acks_late=True,  # a crashed worker's task is redelivered, not lost
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=15 * 60,
    task_soft_time_limit=14 * 60,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 60 * 60},
    worker_hijack_root_logger=False,
    timezone="UTC",
    beat_schedule={
        "sweep-uploads": {
            "task": tasks.EXPIRE_STALE_UPLOADS,
            "schedule": crontab(minute="*/10"),
        },
    },
)


@signals.setup_logging.connect
def _setup_logging(**_: object) -> None:
    configure_logging(settings.log_level, json=settings.log_json)
