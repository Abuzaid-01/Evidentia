"""Test-suite wide configuration. Runs before any Evidentia module reads settings."""

from __future__ import annotations

import os

os.environ["EVIDENTIA_NO_DOTENV"] = "1"
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "AUTH_MODE": "dev",
        "LOG_LEVEL": "WARNING",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://evidentia:evidentia@localhost:5434/evidentia_test",
        ),
        "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"),
        # Fake credentials: signing works offline, nothing is ever sent to Cloudinary in tests.
        "CLOUDINARY_URL": "cloudinary://111122223333:test_secret_value@evidentia-test",
        "CLOUDINARY_ANALYZE_ENABLED": "false",
        "CLOUDINARY_WRITEBACK_ENABLED": "false",
        "CLOUDINARY_UPLOAD_PRESET_IMAGE": "evidentia_image",
        "AI_VISION_PROVIDERS": "mock",
        # deterministic embedder: no model download in tests
        "EMBEDDING_MODEL": "hash-embedder-v1",
        "SEARCH_CLOUDINARY_ENABLED": "false",
    }
)


# --- shared integration fixtures -------------------------------------------------------------------
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

ROOT = Path(__file__).parent


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Fresh schema in the test database (skips the test when Postgres/Redis are not running)."""
    import redis
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    url = os.environ["DATABASE_URL"]
    try:
        engine = create_engine(url)
        engine.connect().close()
        engine.dispose()
        redis.Redis.from_url(os.environ["REDIS_URL"]).ping()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"integration services not reachable ({type(exc).__name__}); run `make setup`")

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return url
