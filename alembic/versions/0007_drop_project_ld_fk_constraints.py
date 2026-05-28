"""Drop hard FK constraints from sla_definitions and evaluation_results to project_ld_config.

project_id becomes a soft cross-service reference (UUID string, no DB-level FK).
This allows SLAs to be created without requiring a project_ld_config row.

Revision ID: 0007_drop_project_ld_fk
Revises: 0006_cleanup
Create Date: 2026-05-28
"""
from __future__ import annotations

from alembic import op

revision = "0007_drop_project_ld_fk"
down_revision = "0006_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_sla_def_project_id",
        "sla_definitions",
        schema="contract",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_eval_results_project_id",
        "evaluation_results",
        schema="contract",
        type_="foreignkey",
    )


def downgrade() -> None:
    op.create_foreign_key(
        "fk_eval_results_project_id",
        "evaluation_results", "project_ld_config",
        ["project_id"], ["project_id"],
        source_schema="contract", referent_schema="contract",
    )
    op.create_foreign_key(
        "fk_sla_def_project_id",
        "sla_definitions", "project_ld_config",
        ["project_id"], ["project_id"],
        source_schema="contract", referent_schema="contract",
        ondelete="CASCADE",
    )
