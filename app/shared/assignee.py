"""Shared helpers for the optional ``assigned_to`` field on
tasks / subtasks (doc 41 follow-up — mirror of the monolith).

A "live, assignable" user is one that is:
  * present in the ``users`` table (no FK coverage on its own — we
    validate at the service layer for a clearer 422 message),
  * has ``status = 'active'`` (inactive users are out of scope), and
  * is not soft-deleted (``deleted_at IS NULL``).

Doc 54: when the caller supplies ``project_id`` and ``caller_user_id``,
the validator additionally enforces, for non-admin callers, that the
assignee be in the **same vendor** as the caller AND hold a
**project-tier role assignment** on that project. admin / super_admin
callers bypass the narrowing (they have global reach by design).

The helper returns the UUID unchanged on success and raises a
``ValidationError`` with a stable message otherwise. Used by both
task and subtask create / update flows.
"""
from typing import Iterable, Dict, Optional

from sqlalchemy import and_, exists
from sqlalchemy.orm import Session

from ..core.errors import ValidationError
from ..infrastructure.db.models.user import UserModel


# Roles that count as "assigned to the project" for the doc-54 gate.
# Per user direction: project-tier scoped roles only — not project_members
# table entries, not org_admin reach via the vendor.
_PROJECT_TIER_ROLES = ("project_admin", "project_member", "division_member")


def validate_assignable_user_id(
    db: Session,
    user_id: str,
    *,
    project_id: Optional[str] = None,
    caller_user_id: Optional[str] = None,
) -> str:
    """Confirm ``user_id`` is assignable. Raises ``ValidationError`` with
    a 422-friendly message if not. Returns the id unchanged on success.

    Layer 1 (always enforced): exists, active, not soft-deleted.

    Layer 2 (enforced only when both ``project_id`` and ``caller_user_id``
    are supplied AND the caller is NOT admin / super_admin):

      * Same vendor — the assignee's ``vendor_id`` on the users row
        must equal the caller's ``vendor_id``.
      * Project-tier membership — the assignee must have a row in
        ``user_role_assignments`` with role in
        ``(project_admin, project_member, division_member)`` and
        ``project_id`` equal to the target project.

    Callers that pre-date doc 54 (omitting both new kwargs) keep the
    Layer-1-only behaviour for back-compat.
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

    # Layer 2 — only when caller passed both ids. Lazy imports inside
    # the function so the legacy callers that don't pass either kwarg
    # don't pay for the RBAC dependency.
    if project_id is None or caller_user_id is None:
        return user_id

    from ..infrastructure.db.repositories.rbac_repository import RbacRepository
    from ..infrastructure.db.models.role import RoleModel
    from ..infrastructure.db.models.user_role_assignment import (
        UserRoleAssignmentModel,
    )

    # admin / super_admin bypass — global tier, no narrowing.
    if RbacRepository(db).user_has_admin_role(caller_user_id):
        return user_id

    # Same vendor — both caller and assignee must have a vendor_id and
    # the two must match. (admin / super_admin already returned above;
    # their vendor_id is typically null and would fail this check.)
    caller_vendor = (
        db.query(UserModel.vendor_id)
        .filter(UserModel.id == caller_user_id)
        .first()
    )
    if caller_vendor is None or caller_vendor[0] is None:
        raise ValidationError(
            "Caller has no vendor binding; cannot determine "
            "organization scope for the assignment."
        )
    assignee_vendor = (
        db.query(UserModel.vendor_id)
        .filter(UserModel.id == user_id)
        .first()
    )
    if (
        assignee_vendor is None
        or assignee_vendor[0] is None
        or assignee_vendor[0] != caller_vendor[0]
    ):
        raise ValidationError(
            f"assignedTo user '{user_id}' is not in your organization. "
            f"You can only assign tasks / subtasks to users in your "
            f"own vendor."
        )

    # Project-tier role on this project.
    has_project_role = (
        db.query(
            exists().where(
                and_(
                    UserRoleAssignmentModel.user_id == user_id,
                    UserRoleAssignmentModel.project_id == project_id,
                    UserRoleAssignmentModel.role_id == RoleModel.id,
                    RoleModel.name.in_(_PROJECT_TIER_ROLES),
                )
            )
        )
        .scalar()
        or False
    )
    if not has_project_role:
        raise ValidationError(
            f"assignedTo user '{user_id}' is not assigned to this "
            f"project. They must first be added as a project_admin, "
            f"project_member, or division_member of the project."
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
