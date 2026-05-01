"""Helpers shared by comments + attachments services.

Polymorphic target verification — given a target_kind + target_id,
confirm the row exists in the appropriate M/A/T/S table and isn't
soft-deleted. Called before every comment/attachment create so we
never persist orphans.
"""
from typing import Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session


# (table_name, id_column) per allowed target_kind. Hardcoded — keeps
# the polymorphic dispatch contained to one place.
_TARGET_TABLES: dict[str, Tuple[str, str]] = {
    "milestone": ("milestones", "id"),
    "activity": ("activities", "id"),
    "task": ("tasks", "id"),
    "subtask": ("subtasks", "id"),
}


def is_valid_target_kind(kind: str) -> bool:
    return kind in _TARGET_TABLES


def target_exists(db: Session, target_kind: str, target_id: str) -> bool:
    """True iff a non-soft-deleted row with this id exists in the target table.

    Uses raw SQL because the table is selected dynamically. Table name
    comes from a hardcoded whitelist (above), so SQL injection is not
    possible — table_name is never user input.
    """
    if not is_valid_target_kind(target_kind):
        return False
    table, id_col = _TARGET_TABLES[target_kind]
    sql = text(
        f"SELECT 1 FROM {table} WHERE {id_col} = :tid "
        f"AND deleted_at IS NULL LIMIT 1"
    )
    row = db.execute(sql, {"tid": target_id}).first()
    return row is not None


# Mapping from URL path segment (plural) to internal target_kind (singular).
URL_KIND_MAP: dict[str, str] = {
    "milestones": "milestone",
    "activities": "activity",
    "tasks": "task",
    "subtasks": "subtask",
}
