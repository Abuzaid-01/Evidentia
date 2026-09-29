"""Process-wide worker dependencies, built once per worker process."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import httpx
import redis
from evidentia_ai.providers import VisionProvider, build_vision_providers
from evidentia_cloudinary import CloudinaryCredentials, configure
from evidentia_cloudinary.analyze import AnalyzeClient
from evidentia_core.config import Settings, get_settings
from evidentia_core.events import EventPublisher
from evidentia_ml.embeddings import Embedder, get_embedder


@dataclass
class WorkerContext:
    settings: Settings
    creds: CloudinaryCredentials | None
    analyze: AnalyzeClient | None
    providers: list[VisionProvider]
    publisher: EventPublisher
    http: httpx.Client
    redis: redis.Redis

    @property
    def use_named(self) -> bool:
        return self.settings.cloudinary_use_named_transformations

    @property
    def embedder(self) -> Embedder | None:
        """Loaded lazily on first use (the model is large); None when embeddings are disabled."""
        if not self.settings.embeddings_enabled:
            return None
        s = self.settings
        return get_embedder(s.embedding_model, s.embedding_device, s.embedding_dim)


@lru_cache
def get_context() -> WorkerContext:
    settings = get_settings()
    creds: CloudinaryCredentials | None = None
    analyze: AnalyzeClient | None = None
    if settings.cloudinary_configured:
        cloud, key, secret = settings.cloudinary_parts()
        creds = CloudinaryCredentials(cloud, key, secret, settings.cloudinary_signature_algorithm)
        configure(creds)
        if settings.cloudinary_analyze_enabled:
            analyze = AnalyzeClient(creds, timeout=settings.ai_request_timeout_seconds)
    return WorkerContext(
        settings=settings,
        creds=creds,
        analyze=analyze,
        providers=build_vision_providers(settings, analyze),
        publisher=EventPublisher(settings.redis_url),
        http=httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True),
        redis=redis.Redis.from_url(settings.redis_url),
    )
