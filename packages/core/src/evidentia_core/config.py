"""Typed application settings, loaded from environment variables and the repo-level `.env`."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
AuthMode = Literal["clerk", "dev"]
VisionProviderName = Literal["cloudinary", "gemini", "groq", "mock"]

MB = 1024 * 1024


def _find_env_file() -> Path | None:
    """Walk up from the working directory to find the repo `.env` (so every service shares one file).

    Tests set EVIDENTIA_NO_DOTENV=1 so a developer's real keys are never used by the test suite.
    """
    if os.environ.get("EVIDENTIA_NO_DOTENV") == "1":
        return None
    here = Path.cwd().resolve()
    for directory in (here, *here.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
        if (directory / "pyproject.toml").is_file() and (directory / "packages").is_dir():
            break
    return None


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(), extra="ignore", env_ignore_empty=True
    )

    # --- application -------------------------------------------------------
    app_name: str = "Evidentia"
    environment: Environment = "local"
    log_level: str = "INFO"
    log_json: bool = False

    # --- infrastructure -----------------------------------------------------
    database_url: str = "postgresql+psycopg://evidentia:evidentia@localhost:5434/evidentia"
    redis_url: str = "redis://localhost:6379/0"
    api_cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    # Public HTTPS base URL of this API (tunnel in local dev, real domain in prod).
    # When set, Cloudinary webhooks are requested for every upload.
    public_api_base_url: str | None = None
    web_base_url: str = "http://localhost:3000"

    # --- auth -----------------------------------------------------------------
    auth_mode: AuthMode = "dev"
    clerk_issuer: str | None = None  # e.g. https://your-app.clerk.accounts.dev
    clerk_jwks_url: str | None = None  # defaults to <issuer>/.well-known/jwks.json
    clerk_authorized_parties: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # --- cloudinary -----------------------------------------------------------
    cloudinary_url: SecretStr | None = None  # cloudinary://<api_key>:<api_secret>@<cloud_name>
    cloudinary_folder_root: str = "evidentia"
    cloudinary_signature_algorithm: Literal["sha1", "sha256"] = "sha1"
    cloudinary_upload_preset_image: str | None = None
    cloudinary_upload_preset_video: str | None = None
    cloudinary_use_named_transformations: bool = True
    cloudinary_use_structured_metadata: bool = False
    cloudinary_analyze_enabled: bool = True
    cloudinary_ocr_enabled: bool = False
    cloudinary_auto_tagging: str | None = None  # e.g. "google_tagging" (add-on must be enabled)
    cloudinary_auto_tagging_threshold: float = 0.6
    cloudinary_webhook_max_age_seconds: int = 7200
    cloudinary_writeback_enabled: bool = True
    # Phase 6. Both are optional accelerators: a permanent failure falls back to keyframes / no speech.
    cloudinary_video_analysis_enabled: bool = True
    cloudinary_video_transcription_enabled: bool = True

    # --- AI -------------------------------------------------------------------
    ai_vision_providers: Annotated[list[VisionProviderName], NoDecode] = [
        "cloudinary",
        "gemini",
        "groq",
    ]
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: SecretStr | None = None
    groq_model: str = "qwen/qwen3.8-27b"  # vision-capable on Groq (Sep 2026)
    ai_request_timeout_seconds: float = 60.0

    # text LLM (query planning, claim validation); tried in order, unconfigured skipped
    llm_text_providers: Annotated[list[Literal["gemini", "groq", "mock"]], NoDecode] = [
        "gemini",
        "groq",
    ]
    gemini_text_model: str = "gemini-2.5-flash"
    groq_text_model: str = "openai/gpt-oss-120b"

    # --- embeddings & search (Phase 3) -----------------------------------------------
    embeddings_enabled: bool = True
    embedding_model: str = "google/siglip-base-patch16-224"
    embedding_dim: int = 768  # must match the vector(768) column (migration 0002)
    embedding_device: str = "cpu"
    embeddings_warmup: bool = False  # load the model at API start instead of on first search
    search_cloudinary_enabled: bool = True
    search_llm_planner_enabled: bool = True
    search_rrf_k: int = 60
    search_candidates_per_retriever: int = 100
    search_visual_min_probability: float = 0.001  # SigLIP calibrated text->image match floor
    search_text_vector_margin: float = 0.12  # keep text-vector hits within this of the best
    # absolute floor for SigLIP text-to-text similarity. Measured on real data (Sep 2026): relevant
    # queries scored >= 0.60, unrelated ones <= 0.49 ("a man eating apple" vs sewer photos: 0.48)
    search_text_vector_min_similarity: float = 0.55

    # --- demo mode ----------------------------------------------------------------
    # One-click workflow for live presentations (/v1/demo/*). Every call is real; approvals are
    # made by a separate "Demo reviewer" user in the same organisation, so four-eyes still holds.
    # Turn off where managers must not be able to fast-track approvals.
    demo_mode_enabled: bool = True

    # --- media policy -----------------------------------------------------------
    max_image_bytes: int = 40 * MB
    max_video_bytes: int = 500 * MB
    max_video_seconds: int = 600
    upload_chunk_bytes: int = 20 * MB
    upload_intent_ttl_hours: int = 24
    sha256_max_bytes: int = 600 * MB

    # --- evidence rules ---------------------------------------------------------
    review_confidence_threshold: float = Field(default=0.75, ge=0, le=1)
    near_duplicate_max_distance: int = Field(default=8, ge=0, le=64)
    site_default_radius_m: int = 1000

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        if isinstance(value, str):
            if value.startswith("postgres://"):
                return value.replace("postgres://", "postgresql+psycopg://", 1)
            if value.startswith("postgresql://") and not value.startswith("postgresql+"):
                return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator(
        "api_cors_origins",
        "clerk_authorized_parties",
        "ai_vision_providers",
        "llm_text_providers",
        mode="before",
    )
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @model_validator(mode="after")
    def _safety(self) -> Settings:
        if (
            self.environment in {"staging", "production"}
            and self.auth_mode == "dev"
            and not self.demo_mode_enabled
        ):
            raise ValueError(
                "AUTH_MODE=dev is only allowed in local/test environments or when DEMO_MODE_ENABLED=true"
            )
        if self.auth_mode == "clerk" and not self.clerk_issuer:
            raise ValueError("AUTH_MODE=clerk requires CLERK_ISSUER")
        return self

    # --- derived ------------------------------------------------------------------
    @property
    def resolved_clerk_jwks_url(self) -> str | None:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        if self.clerk_issuer:
            return self.clerk_issuer.rstrip("/") + "/.well-known/jwks.json"
        return None

    @property
    def sync_database_url(self) -> str:
        return self.database_url

    @property
    def webhook_url(self) -> str | None:
        if not self.public_api_base_url:
            return None
        return self.public_api_base_url.rstrip("/") + "/v1/webhooks/cloudinary"

    @property
    def cloudinary_configured(self) -> bool:
        return self.cloudinary_url is not None

    def cloudinary_parts(self) -> tuple[str, str, str]:
        """Return (cloud_name, api_key, api_secret) parsed from CLOUDINARY_URL."""
        if self.cloudinary_url is None:
            raise RuntimeError("CLOUDINARY_URL is not configured")
        parsed = urlparse(self.cloudinary_url.get_secret_value())
        if parsed.scheme != "cloudinary" or not (
            parsed.hostname and parsed.username and parsed.password
        ):
            raise RuntimeError("CLOUDINARY_URL must look like cloudinary://<key>:<secret>@<cloud>")
        return parsed.hostname, parsed.username, parsed.password


@lru_cache
def get_settings() -> Settings:
    return Settings()
