"""Admin-tier detection for an arbitrary user (not the caller).

The caller's admin status is hydrated onto ``request.state.is_admin`` by the
middleware (see ``app.core.rbac._is_admin``). But some checks need to know
whether a *target* user (e.g. a task/subtask assignee) is admin-tier, which the
request state cannot answer.

This mirrors the canonical definition in user-management
(``RbacRepository.user_has_admin_role``): a user is admin-tier iff they hold
``admin`` or ``super_admin`` at GLOBAL scope —

  * legacy ``users.user_roles`` (global by design), OR
  * ``users.user_role_assignments`` with ``organization_id IS NULL AND
    project_id IS NULL``.

A scoped (org- or project-level) admin/super_admin assignment does NOT count
(Round-8 C5: a scoped admin row must not confer global admin authority).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import Role, UserRole, UserRoleAssignment

_ADMIN_ROLE_NAMES = ("admin", "super_admin")


def is_user_admin_tier(db: Session, user_id: str) -> bool:
    """True iff ``user_id`` holds admin/super_admin at GLOBAL scope."""
    if not user_id:
        return False

    legacy = db.execute(
        select(UserRole.role_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
        .where(Role.name.in_(_ADMIN_ROLE_NAMES))
        .limit(1)
    ).first()
    if legacy is not None:
        return True

    scoped = db.execute(
        select(UserRoleAssignment.id)
        .join(Role, Role.id == UserRoleAssignment.role_id)
        .where(UserRoleAssignment.user_id == user_id)
        .where(UserRoleAssignment.organization_id.is_(None))
        .where(UserRoleAssignment.project_id.is_(None))
        .where(Role.name.in_(_ADMIN_ROLE_NAMES))
        .limit(1)
    ).first()
    return scoped is not None
