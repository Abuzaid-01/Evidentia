#!/usr/bin/env bash
# Render start command for the API web service.
#
# Render's free plan has no background workers, so the Celery worker (with its scheduler, -B) runs
# in this same container, next to the API. It is restarted if it ever exits. Uploads are processed
# while the service is awake; jobs queued while it sleeps wait in Redis and run on the next wake-up.
# To move the worker to its own paid service later, delete the loop below and add a `worker`
# service in render.yaml with the same celery command.
set -euo pipefail

uv run --no-sync alembic upgrade head

(
  while true; do
    uv run --no-sync celery -A evidentia_worker.celery_app worker -B \
      -Q ingest,analysis,maintenance,reports,ml \
      --pool=threads --concurrency=2 --loglevel=INFO \
      --schedule=/tmp/evidentia-celerybeat || true
    echo "celery worker exited; restarting in 5 s" >&2
    sleep 5
  done
) &

exec uv run --no-sync uvicorn evidentia_api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
