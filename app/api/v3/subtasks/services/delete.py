"""Soft-delete a subtask + its nested descendant subtree (doc 24).

For a top-level subtask this is a single-row soft-delete plus dependency
edge cleanup, same as before nesting was a thing. For a subtask with
descendants we collect every descendant id first, soft-delete them all
in one pass, and wipe every dependency edge (incoming + outgoing) for
each descendant — preserving the same "no dangling edges" guarantee the
flat subtree had.
"""
from typing import Optional
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....core.project_lock import assert_task_subtask_writable
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.subtask_repository import SubtaskRepository
from .....shared.dep_block import (
    KIND_SUBTASK,
    collect_external_dep_blockers,
    raise_if_external_blockers,
)


def delete_subtask(db: Session, *, subtask_id: str, current_user_id: Optional[int]) -> None:
    repo = SubtaskRepository(db)
    model = repo.get_model(subtask_id)
    if model is None:
        raise NotFoundError("The subtask could not be found.")
    assert_task_subtask_writable(db, model.project_id)

    # Doc 34: refuse delete if any external dep targets this subtree.
    blockers = collect_external_dep_blockers(
        db,
        root_kind=KIND_SUBTASK,
        root_id=subtask_id,
        project_id=model.project_id,
    )
    raise_if_external_blockers(
        blockers, root_label=model.name, root_kind=KIND_SUBTASK,
    )

    dep_repo = DependencyRepository(db)
    # Collect descendants BEFORE we soft-delete (the read filters on
    # deleted_at IS NULL). Then wipe edges for every id in the subtree.
    descendant_ids = repo.descendant_ids(subtask_id)
    for sid in descendant_ids:
        dep_repo.cascade_remove_subtask_targets(sid, actor_id=current_user_id)
    repo.soft_delete(subtask_id, deleted_by=current_user_id)

    # Doc 33: subtree audit expansion.
    from ...projects.services.audit import ACTION_SUBTASK_DELETE, record_audit
    record_audit(
        db,
        project_id=model.project_id,
        actor_id=current_user_id,
        action=ACTION_SUBTASK_DELETE,
        before={
            "subtask_id": subtask_id,
            "name": model.name,
            "task_id": model.task_id,
        },
        after=None,
    )
    db.commit()
