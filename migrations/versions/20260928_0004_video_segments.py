"""video segment embeddings

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28 18:00:00+00:00

One asset can now carry many segment vectors (a video moment each). Analysis tasks gain
video_visual and speech. Embedding kinds gain segment.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_checks_mentioning(table: str, column: str) -> None:
    op.execute(
        sa.text(  # table/column are constants from this file, never user input
            f"""
            DO $$
            DECLARE r record;
            BEGIN
              FOR r IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = '{table}'
                  AND con.contype = 'c'
                  AND pg_get_constraintdef(con.oid) ILIKE '%{column}%'
              LOOP
                EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', r.conname);
              END LOOP;
            END $$;
            """  # noqa: S608
        )
    )


def upgrade() -> None:
    op.add_column(
        "embeddings",
        sa.Column("segment_key", sa.String(length=80), server_default="", nullable=False),
    )
    op.add_column("embeddings", sa.Column("start_ms", sa.Integer(), nullable=True))
    op.add_column("embeddings", sa.Column("end_ms", sa.Integer(), nullable=True))
    op.drop_constraint("uq_embeddings_asset_id_kind_model", "embeddings", type_="unique")
    op.create_unique_constraint(
        "uq_embeddings_asset_kind_model_segment",
        "embeddings",
        ["asset_id", "kind", "model", "segment_key"],
    )
    _drop_checks_mentioning("embeddings", "kind")
    op.create_check_constraint(
        "ck_embeddings_kind",
        "embeddings",
        "kind IN ('image', 'text', 'segment')",
    )
    _drop_checks_mentioning("analysis_runs", "task")
    op.create_check_constraint(
        "ck_analysis_runs_task",
        "analysis_runs",
        "task IN ('caption', 'quality', 'tagging', 'vision_extract', 'ocr', 'auto_tagging', "
        "'video_visual', 'speech')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_analysis_runs_task", "analysis_runs", type_="check")
    op.create_check_constraint(
        "ck_analysis_runs_task",
        "analysis_runs",
        "task IN ('caption', 'quality', 'tagging', 'vision_extract', 'ocr', 'auto_tagging')",
    )
    op.drop_constraint("ck_embeddings_kind", "embeddings", type_="check")
    op.create_check_constraint("ck_embeddings_kind", "embeddings", "kind IN ('image', 'text')")
    op.drop_constraint("uq_embeddings_asset_kind_model_segment", "embeddings", type_="unique")
    op.create_unique_constraint(
        "uq_embeddings_asset_id_kind_model", "embeddings", ["asset_id", "kind", "model"]
    )
    op.drop_column("embeddings", "end_ms")
    op.drop_column("embeddings", "start_ms")
    op.drop_column("embeddings", "segment_key")
