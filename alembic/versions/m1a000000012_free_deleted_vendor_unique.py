"""Free a deleted vendor's name/code for reuse (Bug #138, org side).

Revision ID: m1a000000012
Revises: m1a000000011
Create Date: 2026-07-12

Bug #138 (org side): mirror the user behaviour (migration r020 in user-svc). A
DELETED (soft-deleted, deleted_at set) vendor's unique fields (name, vendor_code)
must become FREE to reuse for a new vendor; a DEACTIVATED vendor (active=false,
deleted_at NULL) keeps them RESERVED. So scope the uniqueness to live rows —
partial unique indexes ``WHERE deleted_at IS NULL``:

  - soft-deleted vendor -> outside the index -> name/code free for a new vendor
  - deactivated vendor   -> deleted_at NULL   -> still inside -> stays reserved
  - restoring a deleted vendor whose name/code was reused -> unique violation,
    surfaced by the service as a clean "cannot be restored" conflict.

Safe to apply: the existing FULL unique indexes already guarantee every row is
unique, so the narrower partial index has no existing violations.

Downgrade re-tightens to FULL unique indexes; it will fail if by then a deleted
vendor shares a name/code with a live vendor (the new behaviour allows that),
which is the expected cost of reverting this semantics change.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000012"
down_revision = "m1a000000011"
branch_labels = None
depends_on = None

_LIVE = sa.text("deleted_at IS NULL")


def upgrade() -> None:
    op.drop_index("ix_vendors_name", table_name="vendors", schema="masters")
    op.create_index(
        "ix_vendors_name", "vendors", ["name"], unique=True, schema="masters",
        postgresql_where=_LIVE,
    )
    op.drop_index("ix_vendors_vendor_code", table_name="vendors", schema="masters")
    op.create_index(
        "ix_vendors_vendor_code", "vendors", ["vendor_code"], unique=True,
        schema="masters", postgresql_where=_LIVE,
    )


def downgrade() -> None:
    op.drop_index("ix_vendors_name", table_name="vendors", schema="masters")
    op.create_index("ix_vendors_name", "vendors", ["name"], unique=True, schema="masters")
    op.drop_index("ix_vendors_vendor_code", table_name="vendors", schema="masters")
    op.create_index(
        "ix_vendors_vendor_code", "vendors", ["vendor_code"], unique=True, schema="masters",
    )
