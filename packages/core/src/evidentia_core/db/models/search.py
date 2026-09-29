"""Phase 3: embeddings (pgvector) and search logs (for evaluation and learning-to-rank later)."""

from __future__ import annotations

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from evidentia_core.db.base import Base, TenantScoped, Timestamps, UUIDPk
from evidentia_core.domain.enums import EmbeddingKind, SearchFeedbackAction

EMBEDDING_DIM = (
    768  # google/siglip-base-patch16-224; changing models of another size needs a migration
)


class Embedding(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "kind",
            "model",
            "segment_key",
            name="uq_embeddings_asset_kind_model_segment",
        ),
        Index(
            "ix_embeddings_vector_hnsw",
            "vector",
            postgresql_using="hnsw",
            postgresql_ops={"vector": "vector_cosine_ops"},
        ),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[EmbeddingKind]
    model: Mapped[str] = mapped_column(String(120))
    vector: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM))
    source_hash: Mapped[str | None] = mapped_column(
        String(64)
    )  # what was embedded (skip if unchanged)
    # "" for a whole-asset vector. A video span uses "{start_ms}:{end_ms}" so one asset can have
    # many segment vectors and search can return the matching moment.
    segment_key: Mapped[str] = mapped_column(String(80), default="")
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)


class SearchQuery(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "search_queries"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    query: Mapped[str] = mapped_column(Text)
    plan: Mapped[dict[str, Any]]
    result_ids: Mapped[list[Any]]
    retrievers: Mapped[dict[str, Any] | None]  # per-retriever hit counts / timings
    took_ms: Mapped[int]


class SearchFeedback(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "search_feedback"

    query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search_queries.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[SearchFeedbackAction]
    rank: Mapped[int | None]
