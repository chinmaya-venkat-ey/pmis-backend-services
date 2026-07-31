"""Drop the masters.designations catalog (superseded by leave-mgmt rate cards).

Revision ID: m1a000000017
Revises: m1a000000016
Create Date: 2026-07-30

Why:
  The designation catalog was a duplicate of the leave-management designation-rate
  model (`/api/designation-rates`: per project+org roles + per-contract-year rate
  cards), which is the authoritative source. Planned-resource costing now takes
  the rate from that source (via the FE), so the catalog + its
  `designations:read/manage` permissions (removed in user-mgmt r032) are dead.
  The `resource_cost`/`transaction_cost` cost-type seed (m1a000000016) is
  independent and stays.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m1a000000017"
down_revision = "m1a000000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_designations_active", table_name="designations", schema="masters")
    op.drop_index("ix_designations_vendor_id", table_name="designations", schema="masters")
    op.drop_index("ix_designations_vendor_code", table_name="designations", schema="masters")
    op.drop_table("designations", schema="masters")


def downgrade() -> None:
    # Recreate the catalog as it stood at m1a000000015 (per-org + monthly_rate).
    op.create_table(
        "designations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("vendor_id", sa.String(36), nullable=True),
        sa.Column("monthly_rate", sa.Numeric(12, 2), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_designations_vendor_code", "designations", ["vendor_id", "code"], unique=True, schema="masters")
    op.create_index("ix_designations_vendor_id", "designations", ["vendor_id"], schema="masters")
    op.create_index("ix_designations_active", "designations", ["active"], schema="masters")
    op.execute(
        "INSERT INTO masters.designations (id, code, name, active) "
        "VALUES (gen_random_uuid()::text, 'consultant', 'Consultant', true)"
    )
