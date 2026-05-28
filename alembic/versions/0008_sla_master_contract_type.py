"""SLA master table adjustments.

1. Make sla_definitions.project_id nullable — SLA masters are not project-bound.
2. Drop (project_id, sla_ref) unique index — no longer valid when project_id is NULL.
3. Add sla_ref-only unique constraint — global SLA ref must be unique across all masters.
4. Add sla_definitions.contract_type VARCHAR(20) — used to filter SLA masters by contract.

Revision ID: 0008_sla_master_contract_type
Revises: 0007_drop_project_ld_fk
Create Date: 2026-05-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_sla_master_contract_type"
down_revision = "0007_drop_project_ld_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Make project_id nullable
    op.alter_column(
        "sla_definitions",
        "project_id",
        existing_type=sa.String(36),
        nullable=True,
        schema="contract",
    )

    # 2. Replace (project_id, sla_ref) composite unique with sla_ref-only unique
    op.drop_index("ix_sla_def_project_sla_ref", table_name="sla_definitions", schema="contract")
    op.create_index(
        "ix_sla_def_sla_ref",
        "sla_definitions",
        ["sla_ref"],
        unique=True,
        schema="contract",
    )

    # 3. Add contract_type column + index
    op.add_column(
        "sla_definitions",
        sa.Column("contract_type", sa.String(20), nullable=True),
        schema="contract",
    )
    op.create_index(
        "ix_sla_def_contract_type",
        "sla_definitions",
        ["contract_type"],
        schema="contract",
    )


def downgrade() -> None:
    op.drop_index("ix_sla_def_contract_type", table_name="sla_definitions", schema="contract")
    op.drop_column("sla_definitions", "contract_type", schema="contract")

    op.drop_index("ix_sla_def_sla_ref", table_name="sla_definitions", schema="contract")
    op.create_index(
        "ix_sla_def_project_sla_ref",
        "sla_definitions",
        ["project_id", "sla_ref"],
        unique=True,
        schema="contract",
    )

    op.alter_column(
        "sla_definitions",
        "project_id",
        existing_type=sa.String(36),
        nullable=False,
        schema="contract",
    )
