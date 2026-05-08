"""Heal duplicate `position` values among LIVE siblings.

Owns one job: scan a table whose rows have ``(parent_id, position,
deleted_at)``, find any ``(parent_id, position)`` group of more than
one live row, keep the row with the smallest ``id`` at its current
position, and renumber every additional row to the next free slot in
that parent's position space (``current_max_position + 1, +2, ...``).

Called by the doc 22 migration before it adds the partial-unique index
``(parent_id, position) WHERE deleted_at IS NULL`` to milestones,
activities, tasks, and subtasks. Without this heal, any deployment
whose data already had duplicate live positions (legacy bug, manual
import, race in old position-allocation code, etc.) would fail to
apply the index because the constraint can't be created on dirty data.

Also useful as a standalone admin tool — call from a maintenance script
to re-tidy positions after a data import, etc.

Idempotent: runs zero UPDATEs on a table with no duplicates and returns
0. Safe to re-invoke. Single transaction per parent group.

Cross-dialect: uses only standard SQL (GROUP BY / HAVING / MAX) — no
Postgres-specific constructs. Works on SQLite (in-memory tests) and
Postgres (production).
"""
from typing import Iterable, List

from sqlalchemy import text
from sqlalchemy.engine import Connection


def heal_duplicate_positions(
    bind: Connection, table: str, parent_col: str,
) -> int:
    """Renumber duplicate-position siblings in ``table``.

    Args:
        bind: an open SQLAlchemy connection (or alembic ``op.get_bind()``).
        table: the table name (e.g. ``"activities"``).
        parent_col: the parent FK column scoping siblings (e.g.
            ``"milestone_id"`` for activities, ``"activity_id"`` for tasks).

    Returns:
        The number of rows actually renumbered. ``0`` means the table
        already satisfied the per-parent live-position uniqueness invariant.

    Raises:
        Whatever the bind raises on SQL execution. The caller (alembic
        migration) handles transactional rollback.
    """
    # Step 1: find duplicate groups. Each row is a parent that has >1
    # LIVE sibling sharing the same position.
    dup_groups = bind.execute(text(
        f"SELECT {parent_col}, position FROM {table} "
        f"WHERE deleted_at IS NULL "
        f"GROUP BY {parent_col}, position "
        f"HAVING COUNT(*) > 1"
    )).fetchall()

    if not dup_groups:
        return 0

    touched = 0
    for parent_id, dup_pos in dup_groups:
        # Step 2: fetch ids in the dup group, ordered by id (smallest =
        # winner; keeps its position to minimize churn).
        ids: List = [
            r[0] for r in bind.execute(text(
                f"SELECT id FROM {table} "
                f"WHERE {parent_col} = :parent_id "
                f"  AND position = :pos "
                f"  AND deleted_at IS NULL "
                f"ORDER BY id"
            ), {"parent_id": parent_id, "pos": dup_pos}).fetchall()
        ]
        if len(ids) <= 1:
            # Race / staleness — group disappeared between snapshot and
            # this query. Defensive skip.
            continue

        # Step 3: get current max position for this parent. Re-queried
        # per group so renumbering from a previous group on the same
        # parent is reflected here.
        max_pos = bind.execute(text(
            f"SELECT COALESCE(MAX(position), -1) FROM {table} "
            f"WHERE {parent_col} = :parent_id AND deleted_at IS NULL"
        ), {"parent_id": parent_id}).scalar()

        # Step 4: keep ids[0] at dup_pos; renumber every additional row
        # to (max_pos + 1), (max_pos + 2), ... — these slots are by
        # construction higher than any existing position, so they can't
        # collide with another live sibling.
        # NB: ``max_pos or -1`` would be wrong here — when the only live
        # rows for this parent ARE the dup-group at position 0,
        # ``COALESCE(MAX, -1)`` returns 0 (an int Python treats as
        # falsy), and ``0 or -1`` collapses to -1, which would then
        # restart numbering at 0 and re-create the very collision we're
        # trying to fix. Explicit None check is required.
        next_pos = (max_pos if max_pos is not None else -1) + 1
        for orphan_id in ids[1:]:
            bind.execute(text(
                f"UPDATE {table} SET position = :new_pos WHERE id = :id"
            ), {"new_pos": next_pos, "id": orphan_id})
            next_pos += 1
            touched += 1

    return touched


def heal_all_position_duplicates(bind: Connection) -> dict:
    """Run :func:`heal_duplicate_positions` for every M/A/T/S table.

    Convenience for the migration. Returns a ``{table: rows_touched}``
    map so the caller can log the breakdown.
    """
    pairs: Iterable = (
        ("milestones", "project_id"),
        ("activities", "milestone_id"),
        ("tasks",      "activity_id"),
        ("subtasks",   "task_id"),
    )
    return {
        table: heal_duplicate_positions(bind, table, parent_col)
        for table, parent_col in pairs
    }
