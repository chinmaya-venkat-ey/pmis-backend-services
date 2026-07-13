"""Relabel the 'one_time' cost type to 'Out of Pocket Expense'.

Revision ID: m1a000000013
Revises: m1a000000012
Create Date: 2026-07-12

Why:
  FE display label change only (code 'one_time' unchanged): migration
  m1a000000005 set it to 'One-Time (Expense)'; the client wants
  'Out of Pocket Expense' (matches the RFP's out-of-pocket / travel-lodging
  one-time expense wording). Idempotent UPDATE by code; downgrade restores
  the prior label.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000013"
down_revision = "m1a000000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE masters.cost_types SET name = 'Out of Pocket Expense' WHERE code = 'one_time'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE masters.cost_types SET name = 'One-Time (Expense)' WHERE code = 'one_time'"
    ))
