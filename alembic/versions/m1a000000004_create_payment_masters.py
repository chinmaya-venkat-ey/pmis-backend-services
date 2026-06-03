"""Create payment-master catalogs: cost_types + frequencies.

Revision ID: m1a000000004
Revises: m1a000000003
Create Date: 2026-06-03

Why:
  The Project-Finance ("payment") screen drives two dropdowns from masters:
    - cost_types  — the Cost Type selector on each Project-Cost row
                    (built-ins: fixed, one_time).
    - frequencies — the Frequency selector on each Payment-Term row
                    (built-ins: one_time, daily, monthly, quarterly,
                    half_yearly, yearly).

  Both follow the same simple-deactivate model as priorities
  (active=False soft-delete; no deleted_at). Codes are lowercase snake.

  Seed is idempotent (ON CONFLICT (code) DO NOTHING) so the migration is
  safe on a fresh env (seeds rows) or an already-populated one (no-op).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000004"
down_revision = "m1a000000003_priorities_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ cost_types
    op.create_table(
        "cost_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_cost_types_code", "cost_types", ["code"], unique=True, schema="masters")
    op.create_index("ix_cost_types_active", "cost_types", ["active"], schema="masters")
    op.create_index("idx_cost_types_active_code", "cost_types", ["active", "code"], schema="masters")

    # ------------------------------------------------------------------ frequencies
    op.create_table(
        "frequencies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_frequencies_code", "frequencies", ["code"], unique=True, schema="masters")
    op.create_index("ix_frequencies_active", "frequencies", ["active"], schema="masters")
    op.create_index("idx_frequencies_active_code", "frequencies", ["active", "code"], schema="masters")

    # ------------------------------------------------------------------ seed: cost_types
    op.execute(
        sa.text("""
        INSERT INTO masters.cost_types (id, code, name, description, position, active, is_builtin)
        VALUES
            (gen_random_uuid()::text, 'fixed',    'Fixed',    'Fixed cost tied to one or more milestones in a phase', 1, true, true),
            (gen_random_uuid()::text, 'one_time', 'One-Time', 'One-time cost treated as a single deliverable',        2, true, true)
        ON CONFLICT (code) DO NOTHING
        """)
    )

    # ------------------------------------------------------------------ seed: frequencies
    op.execute(
        sa.text("""
        INSERT INTO masters.frequencies (id, code, name, description, position, active, is_builtin)
        VALUES
            (gen_random_uuid()::text, 'one_time',    'One Time',    'Paid once',           1, true, true),
            (gen_random_uuid()::text, 'daily',       'Daily',       'Billed daily',        2, true, true),
            (gen_random_uuid()::text, 'monthly',     'Monthly',     'Billed monthly',      3, true, true),
            (gen_random_uuid()::text, 'quarterly',   'Quarterly',   'Billed quarterly',    4, true, true),
            (gen_random_uuid()::text, 'half_yearly', 'Half Yearly', 'Billed half-yearly',  5, true, true),
            (gen_random_uuid()::text, 'yearly',      'Yearly',      'Billed yearly',       6, true, true)
        ON CONFLICT (code) DO NOTHING
        """)
    )


def downgrade() -> None:
    op.drop_index("idx_frequencies_active_code", table_name="frequencies", schema="masters")
    op.drop_index("ix_frequencies_active", table_name="frequencies", schema="masters")
    op.drop_index("ix_frequencies_code", table_name="frequencies", schema="masters")
    op.drop_table("frequencies", schema="masters")

    op.drop_index("idx_cost_types_active_code", table_name="cost_types", schema="masters")
    op.drop_index("ix_cost_types_active", table_name="cost_types", schema="masters")
    op.drop_index("ix_cost_types_code", table_name="cost_types", schema="masters")
    op.drop_table("cost_types", schema="masters")
