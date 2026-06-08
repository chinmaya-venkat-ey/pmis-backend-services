"""Relabel priorities for display: P1 - High / P2 - Medium / P3 - Low.

Revision ID: m1a000000007
Revises: m1a000000006
Create Date: 2026-06-08

Why:
  Product decision update — the priority ``name`` should read
  "P1 - High / P2 - Medium / P3 - Low". Only the ``name`` field is changed;
  ``description`` and all other fields are left untouched. (This supersedes
  m1a000000003, which had set name = code.)

  Idempotent UPDATE by code; only touches the three canonical priorities.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000007"
down_revision = "m1a000000006"
branch_labels = None
depends_on = None


_LABELS = {
    "P1": "P1 - High",
    "P2": "P2 - Medium",
    "P3": "P3 - Low",
}


def upgrade() -> None:
    for code, name in _LABELS.items():
        op.execute(sa.text(
            "UPDATE masters.priorities SET name = :name WHERE code = :code"
        ).bindparams(name=name, code=code))


def downgrade() -> None:
    # Restore name = code (the prior state). description is not touched.
    for code in _LABELS:
        op.execute(sa.text(
            "UPDATE masters.priorities SET name = :code WHERE code = :code"
        ).bindparams(code=code))
