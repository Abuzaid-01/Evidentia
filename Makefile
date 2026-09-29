.DEFAULT_GOAL := help
SHELL := /bin/bash

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- one-time setup -------------------------------------------------------------------------
setup: ## Install Postgres 17 (+pgvector, PostGIS) and Redis natively, create DBs, install deps
	./infra/local/setup.sh
	@test -f .env || cp .env.example .env
	@test -f apps/web/.env.local || cp apps/web/.env.example apps/web/.env.local
	uv sync --all-packages
	uv run playwright install chromium
	pnpm install
	$(MAKE) migrate

install: ## Install Python + Node dependencies
	uv sync --all-packages
	pnpm install

# --- database ---------------------------------------------------------------------------------
migrate: ## Apply database migrations
	uv run alembic upgrade head

migration: ## Create a migration: make migration m="add claims"
	uv run alembic revision --autogenerate -m "$(m)"

# --- cloudinary --------------------------------------------------------------------------------
cloudinary-bootstrap: ## Create named transformations, signed presets (+ --structured-metadata)
	uv run python infra/cloudinary/bootstrap.py $(args)

demo-seed: ## Upload a folder of demo media (sub-folders = sites): make demo-seed dir=demo-media
	uv run python infra/demo/seed.py $(dir) $(args)

playwright: ## Install headless Chromium for report PDFs (once per machine)
	uv run playwright install chromium

tunnel: ## Public HTTPS URL for Cloudinary webhooks (put it in PUBLIC_API_BASE_URL)
	cloudflared tunnel --url http://localhost:8000

# --- run -------------------------------------------------------------------------------------------
dev: ## Run API + worker + beat + web together
	uv run honcho start

api: ## Run only the API
	uv run uvicorn evidentia_api.main:app --reload --port 8000

worker: ## Run only the worker
	uv run celery -A evidentia_worker.celery_app worker -Q ingest,analysis,maintenance,reports,ml --pool=threads --concurrency=4 --loglevel=INFO

web: ## Run only the web app
	pnpm --filter web dev

# --- quality --------------------------------------------------------------------------------------
test: ## Run all Python tests (integration tests need `make setup`)
	uv run pytest

lint: ## Lint + format check (Python and web)
	uv run ruff check packages services migrations infra
	uv run ruff format --check packages services migrations infra
	pnpm --filter web lint
	pnpm --filter web typecheck

fmt: ## Auto-format Python
	uv run ruff format packages services migrations infra
	uv run ruff check --fix packages services migrations infra

reindex: ## Re-index a project's search (embeddings + text): make reindex project=<uuid>
	uv run celery -A evidentia_worker.celery_app call evidentia.search.reindex_project --args='["$(project)"]'

eval-before-after: ## Pairing benchmark: make eval-before-after dir=demo-pairs (folder with pairs.csv)
	uv run python infra/eval/before_after_eval.py $(if $(dir),$(dir),--synthetic 12) $(args)

loadtest: ## Measured load benchmark (1k assets, concurrent search): writes infra/benchmarks/load_test_report.md
	uv run python infra/benchmarks/load_test.py $(args)

api-types: ## Regenerate the web app's typed API client from the FastAPI schema
	pnpm --filter web gen:api

check: lint test ## Everything CI runs

.PHONY: help setup install migrate migration cloudinary-bootstrap demo-seed playwright tunnel dev api worker web test lint fmt api-types reindex loadtest eval-before-after check
