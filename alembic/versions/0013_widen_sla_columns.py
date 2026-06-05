"""Widen sla_metrics.unit and sla_parameter_values.param_value to match models.

Revision ID: 0013_widen_sla_columns
Revises: 0012_project_ld_bands
Create Date: 2026-06-05

Same class of bug as user-svc's user_code: the original 0001 migration created
these columns narrower than the model declares, so a value within the model's
declared length but over the DB column length truncates at write time
(StringDataRightTruncation -> 500).

  - contract.sla_metrics.unit            VARCHAR(30)  -> VARCHAR(50)
  - contract.sla_parameter_values.param_value VARCHAR(500) -> VARCHAR(1000)

Widening only — never truncates existing values.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_widen_sla_columns"
down_revision = "0012_project_ld_bands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sla_metrics", "unit",
        existing_type=sa.String(length=30), type_=sa.String(length=50),
        existing_nullable=False, schema="contract",
    )
    op.alter_column(
        "sla_parameter_values", "param_value",
        existing_type=sa.String(length=500), type_=sa.String(length=1000),
        existing_nullable=False, schema="contract",
    )


def downgrade() -> None:
    # Intentional no-op. Narrowing these columns back (50->30, 1000->500)
    # would truncation-fail on any value that exceeded the old limit — the
    # exact data this migration widened to accommodate — re-introducing the
    # StringDataRightTruncation bug. Leaving the columns wide is harmless on
    # rollback, so a wholesale downgrade past 0013 is safe.
    pass
