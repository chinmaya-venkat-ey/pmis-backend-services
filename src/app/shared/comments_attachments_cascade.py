"""Cascade soft-delete + restore of comments (doc 35: unified table).

Comments are polymorphic on ``(target_kind, target_id)`` — there's no
FK from this table to the M/A/T/S rows it decorates, so SQL-level
cascades aren't an option. When an M/A/T/S row is soft-deleted the
comments under it would otherwise dangle as orphan rows pointing at a
now-invisible target. Conversely on restore they should come back
together.

Pre-doc-34 there was a sibling ``attachments`` table; this module had
two passes (one per table). Doc 35 collapsed everything onto the
comments row (file metadata is a JSON column on the comment), so this
module is now a single-table walk.

Two helpers, one for each direction:

  - ``cascade_soft_delete_comments_and_attachments`` — stamp ``deleted_at``
    on every comment row anchored at any of the given (kind, id) pairs.
    Idempotent.

  - ``cascade_restore_comments_and_attachments`` — clear ``deleted_at``
    on every comment whose ``deleted_at`` exactly matches the cascade
    timestamp. The timestamp predicate distinguishes "deleted with this
    parent" from "previously soft-deleted before the parent was deleted".

Function names kept stable so the M/A/T/S delete + restore services
don't need to import a new symbol — the rename to "comments only"
would have been cosmetic.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Tuple, Union

from sqlalchemy import or_, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from ..infrastructure.db.models.comment import CommentModel


# A target predicate: either a single id, a list of ids, or a SQLAlchemy
# Select sub-query that resolves to ids (used when the id set is derived
# from another table — e.g. "every activity under this milestone").
TargetIds = Union[str, List[str], Select]


def _id_match(column, ids: TargetIds):
    """Equality for a single id, IN for a list / subquery."""
    if isinstance(ids, str):
        return column == ids
    return column.in_(ids)


def cascade_soft_delete_comments_and_attachments(
    db: Session,
    *,
    targets: List[Tuple[str, TargetIds]],
    deleted_by: Optional[Any],
    now: datetime,
) -> None:
    """Soft-delete every comment row anchored at any of the given
    ``(target_kind, target_id_or_clause)`` pairs.

    ``targets`` is a list like::

        [
            ("milestone", "abc-uuid"),
            ("activity", select(ActivityModel.id).where(...)),
            ("task", task_ids_subquery),
            ("subtask", subtask_ids_subquery),
        ]

    ``now`` and ``deleted_by`` are stamped uniformly across every row
    soft-deleted in this call. Using a single timestamp lets the
    matching restore helper identify exactly which rows to bring back
    when the parent is restored.

    Idempotent — already-soft-deleted rows are skipped.
    """
    if not targets:
        return

    comment_filter = or_(*[
        (CommentModel.target_kind == kind) & _id_match(CommentModel.target_id, ids)
        for kind, ids in targets
    ])

    db.execute(
        update(CommentModel)
        .where(comment_filter, CommentModel.deleted_at.is_(None))
        .values(deleted_at=now, updated_at=now, deleted_by=deleted_by)
    )


def cascade_restore_comments_and_attachments(
    db: Session,
    *,
    targets: List[Tuple[str, TargetIds]],
    cascade_deleted_at: datetime,
) -> None:
    """Inverse of the soft-delete cascade.

    Brings back every comment row whose ``deleted_at`` exactly matches
    ``cascade_deleted_at`` AND that's anchored at one of the given
    ``targets``.

    The timestamp match is the key — it distinguishes rows soft-deleted
    by THIS cascade from rows soft-deleted by an earlier independent
    action. A user who manually deleted a comment yesterday should NOT
    have it spring back to life because their parent milestone was
    deleted+restored today.

    Idempotent — already-live rows are skipped.
    """
    if not targets:
        return

    comment_filter = or_(*[
        (CommentModel.target_kind == kind) & _id_match(CommentModel.target_id, ids)
        for kind, ids in targets
    ])

    db.execute(
        update(CommentModel)
        .where(
            comment_filter,
            CommentModel.deleted_at == cascade_deleted_at,
        )
        .values(deleted_at=None, deleted_by=None)
    )
