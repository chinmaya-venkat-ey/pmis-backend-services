"""Uppercase priority codes (P1/P2/P3) — UI alignment (mirror of monolith).

Revision ID: d2c4f1a9b8e7
Revises: d6b9c4f8a3e1
Create Date: 2026-05-11

Mirror of monolith revision ``d2c4f1a9b8e7_uppercase_priority_codes.py``.
Both services share one Postgres DB but have independent Alembic
chains; this migration runs against the same physical tables and is
idempotent (re-running after monolith already flipped the rows is a
no-op because the new lowercase set is empty).

See monolith revision for full rationale + behaviour notes.
"""
from typing import List, Tuple
from alembic import op
import sqlalchemy as sa


revision = "d2c4f1a9b8e7"
down_revision = "d6b9c4f8a3e1"
branch_labels = None
depends_on = None


_SEED_PAIRS: List[Tuple[str, str]] = [
    ("p1", "P1"),
    ("p2", "P2"),
    ("p3", "P3"),
]


_DEPENDENT_TABLES = ("milestones", "activities", "tasks", "subtasks")


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Flip dependent rows first.
    for table in _DEPENDENT_TABLES:
        for old, new in _SEED_PAIRS:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET priority = :new WHERE priority = :old"
                ),
                {"old": old, "new": new},
            )

    # 2) Flip catalog rows.
    for old, new in _SEED_PAIRS:
        bind.execute(
            sa.text(
                "UPDATE priorities SET code = :new "
                "WHERE code = :old"
            ),
            {"old": old, "new": new},
        )
        bind.execute(
            sa.text(
                "UPDATE priorities SET name = :new "
                "WHERE code = :new AND name = :old"
            ),
            {"old": old, "new": new},
        )


def downgrade() -> None:
    bind = op.get_bind()

    for old, new in _SEED_PAIRS:
        bind.execute(
            sa.text(
                "UPDATE priorities SET name = :old "
                "WHERE code = :new AND name = :new"
            ),
            {"old": old, "new": new},
        )
        bind.execute(
            sa.text(
                "UPDATE priorities SET code = :old "
                "WHERE code = :new"
            ),
            {"old": old, "new": new},
        )

    for table in _DEPENDENT_TABLES:
        for old, new in _SEED_PAIRS:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET priority = :old WHERE priority = :new"
                ),
                {"old": old, "new": new},
            )
