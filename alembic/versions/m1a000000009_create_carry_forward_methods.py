"""Create carry_forward_methods catalog (Project-Finance carry-forward selector).

Revision ID: m1a000000009
Revises: m1a000000008
Create Date: 2026-06-26

Why:
  The carry-forward "method" is now master-driven. Each row is a
  (method, variant) combination with a configurable ``formula`` that computes
  the per-recipient carry-forward amount over a fixed variable set
  (leftover, numRecipients, recipientCycles, totalCycles, recipientPercent) —
  so new variants can be added as config, not code.

  Seeded built-ins (idempotent ON CONFLICT (code) DO NOTHING):
    milestone_evenly / milestone_custom, phase_evenly / phase_custom,
    time_monthly / time_quarterly / time_half_yearly / time_yearly.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000009"
down_revision = "m1a000000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carry_forward_methods",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("variant", sa.String(16), nullable=False),
        sa.Column("formula", sa.String(500), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_carry_forward_methods_code", "carry_forward_methods", ["code"], unique=True, schema="masters")
    op.create_index("ix_carry_forward_methods_active", "carry_forward_methods", ["active"], schema="masters")
    op.create_index("idx_carry_forward_methods_active_code", "carry_forward_methods", ["active", "code"], schema="masters")

    op.execute(
        sa.text("""
        INSERT INTO masters.carry_forward_methods
            (id, code, name, description, method, variant, formula, position, active, is_builtin)
        VALUES
            (gen_random_uuid()::text, 'milestone_evenly', 'Milestone-based - Evenly',
             'Split the leftover equally across subsequent milestones',
             'milestone', 'evenly', 'leftover / numRecipients', 1, true, true),
            (gen_random_uuid()::text, 'milestone_custom', 'Milestone-based - Custom',
             'Custom per-milestone share (percent or amount)',
             'milestone', 'custom', 'leftover * recipientPercent / 100', 2, true, true),
            (gen_random_uuid()::text, 'phase_evenly', 'Phase-based - Evenly',
             'Split the leftover equally across subsequent phases',
             'phase', 'evenly', 'leftover / numRecipients', 3, true, true),
            (gen_random_uuid()::text, 'phase_custom', 'Phase-based - Custom',
             'Custom per-phase share (percent or amount)',
             'phase', 'custom', 'leftover * recipientPercent / 100', 4, true, true),
            (gen_random_uuid()::text, 'time_monthly', 'Time-based - Monthly',
             'Split by each phase''s monthly cycle count',
             'time', 'monthly', 'leftover * recipientCycles / totalCycles', 5, true, true),
            (gen_random_uuid()::text, 'time_quarterly', 'Time-based - Quarterly',
             'Split by each phase''s quarterly cycle count',
             'time', 'quarterly', 'leftover * recipientCycles / totalCycles', 6, true, true),
            (gen_random_uuid()::text, 'time_half_yearly', 'Time-based - Half-Yearly',
             'Split by each phase''s half-yearly cycle count',
             'time', 'half_yearly', 'leftover * recipientCycles / totalCycles', 7, true, true),
            (gen_random_uuid()::text, 'time_yearly', 'Time-based - Yearly',
             'Split by each phase''s yearly cycle count',
             'time', 'yearly', 'leftover * recipientCycles / totalCycles', 8, true, true)
        ON CONFLICT (code) DO NOTHING
        """)
    )


def downgrade() -> None:
    op.drop_index("idx_carry_forward_methods_active_code", table_name="carry_forward_methods", schema="masters")
    op.drop_index("ix_carry_forward_methods_active", table_name="carry_forward_methods", schema="masters")
    op.drop_index("ix_carry_forward_methods_code", table_name="carry_forward_methods", schema="masters")
    op.drop_table("carry_forward_methods", schema="masters")
