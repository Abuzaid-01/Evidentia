"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import structlog
from evidentia_ai.text_llm import build_text_llms
from evidentia_cloudinary import CloudinaryCredentials, configure
from evidentia_core.config import Settings, get_settings
from evidentia_core.db.session import async_engine
from evidentia_core.logging import configure_logging
from evidentia_ml.embeddings import Embedder, get_embedder
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from evidentia_api.auth.verifiers import build_verifier
from evidentia_api.errors import install_error_handlers
from evidentia_api.middleware import RequestContextMiddleware
from evidentia_api.routers import (
    assets,
    audit,
    before_after,
    campaigns,
    claims,
    demo,
    events,
    health,
    me,
    projects,
    reports,
    review,
    search,
    share,
    uploads,
    webhooks,
)

log = structlog.get_logger("evidentia.api")


def _cloudinary(settings: Settings) -> CloudinaryCredentials | None:
    if not settings.cloudinary_configured:
        return None
    cloud, key, secret = settings.cloudinary_parts()
    creds = CloudinaryCredentials(cloud, key, secret, settings.cloudinary_signature_algorithm)
    configure(creds)
    return creds


def _embedder(settings: Settings) -> Embedder | None:
    if not settings.embeddings_enabled:
        return None
    from evidentia_core.db.models.search import EMBEDDING_DIM

    if settings.embedding_dim != EMBEDDING_DIM:
        raise RuntimeError(
            f"EMBEDDING_DIM={settings.embedding_dim} but the database column is {EMBEDDING_DIM}"
        )
    return get_embedder(settings.embedding_model, settings.embedding_device, settings.embedding_dim)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "api_starting",
            environment=settings.environment,
            auth_mode=settings.auth_mode,
            cloudinary=app.state.cloudinary is not None,
            webhooks=settings.webhook_url is not None,
            embeddings=settings.embedding_model if app.state.embedder else "disabled",
            text_llms=[llm.name for llm in app.state.text_llms],
        )
        if app.state.embedder is not None and settings.embeddings_warmup:
            await anyio.to_thread.run_sync(app.state.embedder.embed_texts, ["warm up"])
        yield
        await async_engine().dispose()

    app = FastAPI(
        title="Evidentia API",
        version="0.1.0",
        description=(
            "Evidence platform for field media: signed Cloudinary ingestion, AI enrichment, "
            "verification and traceable reporting."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.cloudinary = _cloudinary(settings)
    app.state.verifier = build_verifier(settings)
    app.state.embedder = _embedder(settings)
    app.state.text_llms = build_text_llms(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    for router in (
        health.router,
        me.router,
        projects.router,
        uploads.router,
        assets.router,
        search.router,
        review.router,
        claims.router,
        before_after.router,
        campaigns.router,
        reports.router,
        demo.router,
        events.router,
        audit.router,
        webhooks.router,
        share.router,
    ):
        app.include_router(router)
    return app


app = create_app()
