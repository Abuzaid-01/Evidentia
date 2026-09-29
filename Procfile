api: uv run uvicorn evidentia_api.main:app --reload --port 8000 --reload-dir packages --reload-dir services/api
worker: uv run celery -A evidentia_worker.celery_app worker -Q ingest,analysis,maintenance,reports,ml --pool=threads --concurrency=4 --loglevel=INFO
beat: uv run celery -A evidentia_worker.celery_app beat --loglevel=WARNING --schedule=/tmp/evidentia-celerybeat
web: pnpm --filter web dev
