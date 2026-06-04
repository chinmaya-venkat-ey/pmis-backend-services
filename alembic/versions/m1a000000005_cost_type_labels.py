"""Relabel cost-type display names.

Revision ID: m1a000000005
Revises: m1a000000004
Create Date: 2026-06-04

Why:
  FE display label change only (codes unchanged):
    - fixed     : 'Fixed'    -> 'Fixed (Delivery Cost)'
    - one_time  : 'One-Time' -> 'One-Time (Expense)'

  Idempotent UPDATE by code. Existing deployments get the new labels; fresh
  installs seed the old labels via m1a000000004 and this migration updates
  them, so the final state is identical either way.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000005"
down_revision = "m1a000000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE masters.cost_types SET name = 'Fixed (Delivery Cost)' WHERE code = 'fixed'"
    ))
    op.execute(sa.text(
        "UPDATE masters.cost_types SET name = 'One-Time (Expense)' WHERE code = 'one_time'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE masters.cost_types SET name = 'Fixed' WHERE code = 'fixed'"
    ))
    op.execute(sa.text(
        "UPDATE masters.cost_types SET name = 'One-Time' WHERE code = 'one_time'"
    ))
