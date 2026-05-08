"""Shared helpers for the optional ``assigned_to`` field on
tasks / subtasks (doc 41 follow-up — mirror of the monolith).

A "live, assignable" user is one that is:
  * present in the ``users`` table (no FK coverage on its own — we
    validate at the service layer for a clearer 422 message),
  * has ``status = 'active'`` (inactive users are out of scope), and
  * is not soft-deleted (``deleted_at IS NULL``).

The helper returns the UUID unchanged on success and raises a
``ValidationError`` with a stable message otherwise. Used by both
task and subtask create / update flows.
"""
from typing import Iterable, Dict, Optional

from sqlalchemy.orm import Session

from ..core.errors import ValidationError
from ..infrastructure.db.models.user import UserModel


def validate_assignable_user_id(db: Session, user_id: str) -> str:
    """Confirm ``user_id`` is a live, active user. Raises ``ValidationError``
    with a 422-friendly message if not. Returns the id unchanged on success.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValidationError(
            "assignedTo must be a non-empty user UUID string."
        )
    row = (
        db.query(UserModel.id, UserModel.status, UserModel.deleted_at)
        .filter(UserModel.id == user_id)
        .first()
    )
    if row is None:
        raise ValidationError(
            f"assignedTo user '{user_id}' does not exist."
        )
    _id, status, deleted_at = row
    if deleted_at is not None:
        raise ValidationError(
            f"assignedTo user '{user_id}' is deleted and cannot be "
            "assigned. Restore the user first or pick a different one."
        )
    if (status or "").lower() != "active":
        raise ValidationError(
            f"assignedTo user '{user_id}' is not active "
            f"(current status: '{status}'). Pick an active user."
        )
    return user_id


def display_name_of(user: UserModel) -> Optional[str]:
    """Resolve a human display name for the assignee dropdown / response.

    Order of preference:
      1. ``first_name + last_name`` (trimmed, joined with one space)
      2. ``first_name`` alone, or ``last_name`` alone
      3. ``login`` (always present, NOT NULL on the column)

    Returns ``None`` only if the input is ``None``.
    """
    if user is None:
        return None
    fn = (user.first_name or "").strip()
    ln = (user.last_name or "").strip()
    if fn and ln:
        return f"{fn} {ln}"
    if fn:
        return fn
    if ln:
        return ln
    return user.login


def bulk_user_name_lookup(
    db: Session, user_ids: Iterable[str],
) -> Dict[str, str]:
    """Return ``{user_id: display_name}`` for the given UUIDs in a single
    query. Useful for the tree endpoint and the list responses where many
    rows share a small set of assignees.

    Soft-deleted users still resolve so legacy rows that referenced them
    don't show ``null`` names. (The validator blocks new assignments to
    deleted users at write time.)
    """
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    out: Dict[str, str] = {}
    rows = (
        db.query(
            UserModel.id, UserModel.first_name, UserModel.last_name,
            UserModel.login,
        )
        .filter(UserModel.id.in_(ids))
        .all()
    )
    for uid, fn, ln, login in rows:
        fn = (fn or "").strip()
        ln = (ln or "").strip()
        if fn and ln:
            out[uid] = f"{fn} {ln}"
        elif fn:
            out[uid] = fn
        elif ln:
            out[uid] = ln
        else:
            out[uid] = login
    return out
