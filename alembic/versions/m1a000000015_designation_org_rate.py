"""Make designations per-organization + add a monthly rate.

Revision ID: m1a000000015
Revises: m1a000000014
Create Date: 2026-07-28

Why:
  Planned-resource costing needs a per-org designation with a per-month rate
  (monthly_rate × months × quantity). Add ``vendor_id`` (→ masters.vendors.id;
  NULL = global/template) + ``monthly_rate``, and change uniqueness from global
  ``(code)`` to per-org ``(vendor_id, code)`` so each organization can keep its own
  designations at its own rates. The seeded "consultant" row stays global
  (vendor_id NULL).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m1a000000015"
down_revision = "m1a000000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("designations", sa.Column("vendor_id", sa.String(36), nullable=True), schema="masters")
    op.add_column("designations", sa.Column("monthly_rate", sa.Numeric(12, 2), nullable=True), schema="masters")
    # Global-unique(code) -> per-org unique(vendor_id, code).
    op.drop_index("ix_designations_code", table_name="designations", schema="masters")
    op.create_index(
        "ix_designations_vendor_code", "designations", ["vendor_id", "code"],
        unique=True, schema="masters",
    )
    op.create_index("ix_designations_vendor_id", "designations", ["vendor_id"], schema="masters")


def downgrade() -> None:
    op.drop_index("ix_designations_vendor_id", table_name="designations", schema="masters")
    op.drop_index("ix_designations_vendor_code", table_name="designations", schema="masters")
    op.create_index("ix_designations_code", "designations", ["code"], unique=True, schema="masters")
    op.drop_column("designations", "monthly_rate", schema="masters")
    op.drop_column("designations", "vendor_id", schema="masters")
