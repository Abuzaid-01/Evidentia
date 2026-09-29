"""campaigns and share links

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28 17:45:00.000000+00:00

Phase 8. Campaign Studio assets (social aspect ratios, text overlays, brand frames, generative flags)
and external read-only share links with tenant isolation and RLS.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("headline", sa.String(length=300), nullable=False),
        sa.Column("stat_text", sa.String(length=200), nullable=True),
        sa.Column("brand_tag", sa.String(length=100), nullable=True),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("pair_id", sa.UUID(), nullable=True),
        sa.Column("claim_id", sa.UUID(), nullable=True),
        sa.Column("metric_id", sa.UUID(), nullable=True),
        sa.Column("formats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("generative", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("renditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["metric_id"], ["metrics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pair_id"], ["before_after_pairs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_campaigns_asset_id"), "campaigns", ["asset_id"], unique=False)
    op.create_index(
        op.f("ix_campaigns_organization_id"), "campaigns", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_campaigns_project_id"), "campaigns", ["project_id"], unique=False)
    op.create_index(
        "ix_campaigns_project_created", "campaigns", ["project_id", "created_at"], unique=False
    )

    op.create_table(
        "share_links",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_share_links_organization_id"), "share_links", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_share_links_project_id"), "share_links", ["project_id"], unique=False)
    op.create_index("ix_share_links_project", "share_links", ["project_id"], unique=False)
    op.create_index("ix_share_links_target_id", "share_links", ["target_id"], unique=False)
    op.create_index(op.f("ix_share_links_token"), "share_links", ["token"], unique=True)
    op.create_index("ix_share_links_token_uniq", "share_links", ["token"], unique=True)

    # Enable Row-Level Security
    for tbl in ("campaigns", "share_links"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {tbl}
            USING (
                current_setting('app.rls_bypass', true) = 'on'
                OR organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
            )
            WITH CHECK (
                current_setting('app.rls_bypass', true) = 'on'
                OR organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
            )
            """
        )


def downgrade() -> None:
    for tbl in ("campaigns", "share_links"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
    op.drop_table("share_links")
    op.drop_table("campaigns")
