"""Create payment_types catalog (milestone Payment Type dropdown).

Revision ID: m1a000000008
Revises: m1a000000007
Create Date: 2026-06-17

Why:
  Milestones gain a "Payment Type" selector driven from masters. Same
  simple-deactivate model as cost_types / frequencies (active=False
  soft-delete; no deleted_at). Codes are lowercase snake.

  Built-ins seeded: partial_payment, complete_payment. More may be added
  later via the /master/payment-types endpoints.

  Seed is idempotent (ON CONFLICT (code) DO NOTHING) so it is safe on a
  fresh env (seeds rows) or an already-populated one (no-op).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000008"
down_revision = "m1a000000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_types",
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
    op.create_index("ix_payment_types_code", "payment_types", ["code"], unique=True, schema="masters")
    op.create_index("ix_payment_types_active", "payment_types", ["active"], schema="masters")
    op.create_index("idx_payment_types_active_code", "payment_types", ["active", "code"], schema="masters")

    op.execute(
        sa.text("""
        INSERT INTO masters.payment_types (id, code, name, description, position, active, is_builtin)
        VALUES
            (gen_random_uuid()::text, 'partial_payment',  'Partial Payment',  'Milestone billed in part',  1, true, true),
            (gen_random_uuid()::text, 'complete_payment', 'Complete Payment', 'Milestone billed in full',  2, true, true)
        ON CONFLICT (code) DO NOTHING
        """)
    )


def downgrade() -> None:
    op.drop_index("idx_payment_types_active_code", table_name="payment_types", schema="masters")
    op.drop_index("ix_payment_types_active", table_name="payment_types", schema="masters")
    op.drop_index("ix_payment_types_code", table_name="payment_types", schema="masters")
    op.drop_table("payment_types", schema="masters")
