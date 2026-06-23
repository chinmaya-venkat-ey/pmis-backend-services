"""Change `phase` from integer to string on the payment tables.

Revision ID: p1a000000014
Revises: p1a000000013
Create Date: 2026-06-17

Why:
  The finance "phase" identifier on cost items (and the payment terms / QRG
  rows that group by it) becomes a free-text label instead of an integer, so
  callers can use phase names like "Phase A" rather than only 1, 2, 3.

  `phase` is the shared grouping key across project_cost_items,
  project_payment_terms and project_phase_qrg, so all three are widened
  together to keep grouping/joins consistent. Existing integer values are
  cast to their text form (1 -> '1') via ``USING phase::text``; nullability
  is preserved (cost_items / payment_terms stay nullable; phase_qrg stays
  NOT NULL).

  Note: phase ordering on the payment page is now lexical (text), e.g.
  '10' sorts before '2'. Acceptable for free-text phase labels.
"""
from __future__ import annotations

from alembic import op


revision: str = "p1a000000014"
down_revision: str = "p1a000000013"
branch_labels = None
depends_on = None


_TABLES = ("project_cost_items", "project_payment_terms", "project_phase_qrg")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE project.{table} "
            f"ALTER COLUMN phase TYPE varchar(64) USING phase::text"
        )


def downgrade() -> None:
    # Reverses the cast; fails if any phase holds a non-numeric label.
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE project.{table} "
            f"ALTER COLUMN phase TYPE integer USING phase::integer"
        )
