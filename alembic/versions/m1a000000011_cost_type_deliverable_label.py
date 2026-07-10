"""Relabel the 'fixed' cost type to 'Deliverable cost'.

Revision ID: m1a000000011
Revises: m1a000000010
Create Date: 2026-07-10

Why:
  FE display label change only (code unchanged):
    - fixed : 'Fixed (Delivery Cost)' -> 'Deliverable cost'

  Idempotent UPDATE by code. Downgrade restores the previous label set by
  m1a000000005 ('Fixed (Delivery Cost)').
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000011"
down_revision = "m1a000000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE masters.cost_types SET name = 'Deliverable cost' WHERE code = 'fixed'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE masters.cost_types SET name = 'Fixed (Delivery Cost)' WHERE code = 'fixed'"
    ))
