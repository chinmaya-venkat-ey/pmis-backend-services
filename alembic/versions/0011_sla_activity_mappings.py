"""Many-to-many mapping between SLA masters and external activities.

Activity entity is owned by PMIS-Project-management; only the activity_id is
stored here as a soft FK. The overrides JSONB holds per-mapping configuration
(t_anchor_date, actual_start_date, actual_end_date, ld_base_amount, ...).
Override keys are extensible — they evolve as requirements solidify, without
needing a schema migration.

Revision ID: 0011_sla_activity_mappings
Revises: 0010_data_fields_all_contracts
Create Date: 2026-05-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_sla_activity_mappings"
down_revision = "0010_data_fields_all_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sla_activity_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("sla_id", sa.String(36), nullable=False),
        sa.Column(
            "overrides",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_until", sa.Date, nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["sla_id"], ["contract.sla_definitions.id"],
            ondelete="RESTRICT", name="fk_sam_sla_id",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','INACTIVE','RETIRED')",
            name="ck_sam_status",
        ),
        schema="contract",
    )
    op.create_index(
        "ix_sam_activity_id",
        "sla_activity_mappings",
        ["activity_id"],
        schema="contract",
    )
    op.create_index(
        "ix_sam_sla_id",
        "sla_activity_mappings",
        ["sla_id"],
        schema="contract",
    )
    op.create_index(
        "ix_sam_status",
        "sla_activity_mappings",
        ["status"],
        schema="contract",
    )
    op.create_index(
        "uq_sam_activity_sla_effective",
        "sla_activity_mappings",
        ["activity_id", "sla_id", "effective_from"],
        unique=True,
        schema="contract",
    )


def downgrade() -> None:
    op.drop_index("uq_sam_activity_sla_effective", table_name="sla_activity_mappings", schema="contract")
    op.drop_index("ix_sam_status", table_name="sla_activity_mappings", schema="contract")
    op.drop_index("ix_sam_sla_id", table_name="sla_activity_mappings", schema="contract")
    op.drop_index("ix_sam_activity_id", table_name="sla_activity_mappings", schema="contract")
    op.drop_table("sla_activity_mappings", schema="contract")
