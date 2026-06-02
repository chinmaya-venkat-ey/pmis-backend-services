"""Cascade soft-delete + restore helpers for the project subtree.

The project hierarchy is::

    Project → Milestones → Activities → Tasks → Subtasks (recursive)

with a 1:1 ``*_resource`` sidecar on A/T/S.

When a row is soft-deleted, every still-live descendant + its resources
get stamped with the SAME ``deleted_at`` value (the "cascade event
timestamp"). On restore, every descendant whose ``deleted_at`` exactly
matches the parent's cascade timestamp is restored too — descendants
soft-deleted in earlier events stay deleted.

These helpers are pure UPDATE emitters keyed off (Model, where_clauses)
pairs. Per-repository cascade methods compose them; the repos own the
subtree-snapshotting logic, the helpers own the UPDATE pattern. This
keeps the cascade SQL idiom in one place without bleeding cross-model
imports into a shared layer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Tuple

from sqlalchemy import update
from sqlalchemy.orm import Session


CascadeTargets = Iterable[Tuple[type, List]]
"""Sequence of ``(model, where_clauses)`` — each entry describes one
subtree slice to be cascaded. ``where_clauses`` is a list of SQLAlchemy
column expressions (any iterable accepted by ``.where(*clauses)``)."""


def stamp_deleted(db: Session, targets: CascadeTargets, *, when: datetime) -> None:
    """Mark every still-live row matching each ``(model, where_clauses)``
    entry with ``deleted_at = when``. Already-deleted rows are skipped —
    so the operation is idempotent and never overwrites an earlier
    cascade event's timestamp.
    """
    for model, where_clauses in targets:
        db.execute(
            update(model)
            .where(*where_clauses, model.deleted_at.is_(None))
            .values(deleted_at=when)
        )


def clear_deleted(db: Session, targets: CascadeTargets, *, cascade_ts: datetime) -> None:
    """Restore every row matching each ``(model, where_clauses)`` entry
    whose ``deleted_at`` exactly equals ``cascade_ts`` — i.e. that was
    deleted as part of the same cascade event. Rows soft-deleted in an
    earlier (or later) event are left untouched.
    """
    for model, where_clauses in targets:
        db.execute(
            update(model)
            .where(*where_clauses, model.deleted_at == cascade_ts)
            .values(deleted_at=None)
        )
