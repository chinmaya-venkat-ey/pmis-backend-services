"""Doc 44 round 6 — vendor → (project, role) → users matrix helpers.

The FE manages per-vendor role assignments through a single
``user_assignments`` array on PATCH/POST /vendors. Each entry is a
``(project_id, role, user_ids[])`` tuple representing the desired
state — existing rows in ``user_role_assignments`` for that
(project, role) are reconciled to match exactly.

Two helpers live here:

  * :func:`apply_vendor_user_assignments` — write-side.
    Validates project ownership + role names, then for each entry
    diffs current-vs-desired and applies the minimum set of inserts
    + deletes via the ``user_role_assignments`` table.

  * :func:`user_assignments_for_vendor` — read-side. Returns the
    same shape from existing rows so GET /vendors and
    GET /vendors/{id} can echo back what was set.

Role string handling: callers may send the FE display label
("Project Admin") OR the canonical name ("project_admin"); the
helpers normalize either form. Display labels are also used on
the read-side response so the FE form can re-render its picker
without translating.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ....infrastructure.db.models.project_vendor import ProjectVendorModel
from ....infrastructure.db.models.role import RoleModel
from ....infrastructure.db.models.user import UserModel
from ....infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)


# Role names that are legitimate at project scope. Any other role name
# in user_assignments → 422.
_PROJECT_TIER_ROLES = ("project_admin", "project_member", "division_member")

# FE display labels ↔ canonical names. Lower-cased keys for case
# insensitive lookup.
_LABEL_TO_NAME: Dict[str, str] = {
    "project admin": "project_admin",
    "project_admin": "project_admin",
    "project member": "project_member",
    "project_member": "project_member",
    "division member": "division_member",
    "division_member": "division_member",
}

_NAME_TO_LABEL: Dict[str, str] = {
    "project_admin": "Project Admin",
    "project_member": "Project Member",
    "division_member": "Division Member",
}


def _normalize_role(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _LABEL_TO_NAME.get(str(raw).strip().lower())


def _vendor_project_ids(db: Session, vendor_id: str) -> List[str]:
    rows = (
        db.query(ProjectVendorModel.project_id)
        .filter(ProjectVendorModel.vendor_id == vendor_id)
        .all()
    )
    return [r[0] for r in rows]


def apply_vendor_user_assignments(
    db: Session,
    vendor_id: str,
    assignments: List[Dict[str, Any]],
    *,
    actor_id: Optional[str] = None,
) -> None:
    """Reconcile ``user_role_assignments`` rows for this vendor's
    projects to match the supplied ``assignments`` matrix.

    Raises ``ValueError`` (caller maps to 422) on validation issues:
      * unknown / non-project-tier role
      * project_id not owned by ``vendor_id``
      * unknown user_id

    The function flushes within the caller's transaction; the caller
    is responsible for commit / rollback. Idempotent on retry — the
    diff is recomputed each call so re-sending the same body is a
    no-op.
    """
    if not assignments:
        return

    owned_pids = set(_vendor_project_ids(db, vendor_id))

    # Build desired state: { (project_id, role_name): set(user_ids) }.
    desired: Dict[tuple, set] = {}
    for entry in assignments:
        pid = entry.get("project_id") or entry.get("projectId")
        role_raw = entry.get("role")
        user_ids = entry.get("user_ids") or entry.get("userIds") or []
        role_name = _normalize_role(role_raw)
        if not role_name or role_name not in _PROJECT_TIER_ROLES:
            raise ValueError(
                f"Invalid role '{role_raw}' in user_assignments — must be "
                "one of: Project Admin, Project Member, Division Member."
            )
        if not pid:
            raise ValueError(
                "user_assignments entry missing project_id."
            )
        if pid not in owned_pids:
            raise ValueError(
                f"Project {pid} is not owned by vendor {vendor_id}; "
                "cannot wire role assignments to it via this endpoint."
            )
        key = (pid, role_name)
        desired.setdefault(key, set()).update(uid for uid in user_ids if uid)

    # Validate user existence in one query.
    all_user_ids = {uid for users in desired.values() for uid in users}
    if all_user_ids:
        found = {
            uid for (uid,) in (
                db.query(UserModel.id)
                .filter(UserModel.id.in_(all_user_ids))
                .filter(UserModel.deleted_at.is_(None))
                .all()
            )
        }
        missing = all_user_ids - found
        if missing:
            raise ValueError(
                f"Unknown user(s) in user_assignments: {sorted(missing)}"
            )

    # Resolve role names → role_ids in one query.
    role_id_by_name = {
        r.name: r.id
        for r in (
            db.query(RoleModel)
            .filter(RoleModel.name.in_(_PROJECT_TIER_ROLES))
            .all()
        )
    }

    # For each (project, role) tuple, diff existing-vs-desired.
    # Track users who get a NEW assignment in this PATCH so we can
    # update their users.vendor_id afterwards (round 11c).
    newly_granted_user_ids: set = set()
    for (pid, role_name), wanted_users in desired.items():
        role_id = role_id_by_name.get(role_name)
        if role_id is None:
            # Should not happen on a healthy DB — every name is one of
            # the seeded built-ins. Treat as internal.
            raise ValueError(
                f"Role '{role_name}' is not seeded — cannot apply assignments."
            )
        existing_rows = (
            db.query(UserRoleAssignmentModel)
            .filter(
                UserRoleAssignmentModel.role_id == role_id,
                UserRoleAssignmentModel.project_id == pid,
            )
            .all()
        )
        existing_users = {r.user_id: r for r in existing_rows}

        # Revoke users no longer wanted.
        for uid, row in existing_users.items():
            if uid not in wanted_users:
                db.delete(row)

        # Grant users not yet present.
        for uid in wanted_users:
            if uid not in existing_users:
                db.add(UserRoleAssignmentModel(
                    user_id=uid,
                    role_id=role_id,
                    project_id=pid,
                    organization_id=None,
                    created_by=actor_id,
                ))
                newly_granted_user_ids.add(uid)

    # Round 11c — bind newly-granted users to this vendor when they
    # don't already have a vendor mapping OR have a stale one. Tester
    # flagged that users assigned via this matrix were appearing with
    # no primary vendor (or a wrong one), which broke downstream
    # vendor-scoped lookups (round-7 GET /users filter, the FE's
    # Org Mgmt user list, etc.). Pre-existing assignments are left
    # alone so a user who was already correctly bound stays bound.
    if newly_granted_user_ids:
        users_to_bind = (
            db.query(UserModel)
            .filter(UserModel.id.in_(newly_granted_user_ids))
            .all()
        )
        for u in users_to_bind:
            current = getattr(u, "vendor_id", None)
            if current is None or current != vendor_id:
                u.vendor_id = vendor_id

    db.flush()


def user_assignments_for_vendor(
    db: Session, vendor_id: str,
) -> List[Dict[str, Any]]:
    """Read-side: return the per-(project, role) user matrix for every
    project owned by ``vendor_id``. Roles use FE display labels so the
    response shape mirrors the create/update body.

    Per entry the response carries:

      * ``project_id`` (uuid)
      * ``role``       (FE display label)
      * ``user_ids[]`` — list of user UUIDs (legacy, kept for the
        round-6 wire contract)
      * ``users[]``    — parallel list of ``{id, login, firstName,
        lastName, email}`` so the FE can render the user picker
        without an extra ``GET /users`` round-trip per id (doc 46
        round 10c).

    The two arrays are guaranteed to be the same length and ordered
    identically — ``users[i].id == user_ids[i]``.
    """
    project_ids = _vendor_project_ids(db, vendor_id)
    if not project_ids:
        return []

    rows = (
        db.query(
            UserRoleAssignmentModel.project_id,
            RoleModel.name,
            UserRoleAssignmentModel.user_id,
            UserModel.login,
            UserModel.first_name,
            UserModel.last_name,
            UserModel.email,
        )
        .join(RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id)
        .join(UserModel, UserModel.id == UserRoleAssignmentModel.user_id)
        .filter(
            UserRoleAssignmentModel.project_id.in_(project_ids),
            RoleModel.name.in_(_PROJECT_TIER_ROLES),
            UserModel.deleted_at.is_(None),
        )
        .order_by(UserRoleAssignmentModel.project_id, RoleModel.name, UserModel.login)
        .all()
    )
    grouped: Dict[tuple, List[Dict[str, Any]]] = {}
    for project_id, role_name, user_id, login, first_name, last_name, email in rows:
        key = (project_id, role_name)
        grouped.setdefault(key, []).append({
            "id": user_id,
            "login": login,
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
        })

    # Round 11d — always emit a row for every (project, role) combo
    # the FE renders (Project Admin + Project Member) for every project
    # owned by the vendor, even when no users hold that role yet.
    # Tester observed that adding the first PM to a project visually
    # "deleted" the PA row because the FE only rendered roles present
    # in the response — and a project that previously had only PA rows
    # would lose its bucket schema after a PATCH that only changed PM.
    # Returning empty buckets keeps the FE state stable across edits.
    # ``division_member`` is omitted from the always-emit set because
    # the FE doesn't render it on the Project Mapping screen.
    _ALWAYS_EMIT = ("project_admin", "project_member")
    out: List[Dict[str, Any]] = []
    for pid in sorted(project_ids):
        for role_name in _ALWAYS_EMIT:
            users = grouped.get((pid, role_name), [])
            out.append({
                "project_id": pid,
                "role": _NAME_TO_LABEL.get(role_name, role_name),
                # ``user_ids`` kept for backwards-compat with the round-6
                # wire shape. ``users`` is the new parallel-with-context
                # array — same order, fully-hydrated per row.
                "user_ids": [u["id"] for u in users],
                "users": users,
            })
    # Surface any division_member rows that DO have users (even though
    # not auto-emitted when empty) so the legacy wire contract stays
    # honoured for callers that do read DM assignments.
    for (pid, role_name), users in grouped.items():
        if role_name == "division_member" and users:
            out.append({
                "project_id": pid,
                "role": _NAME_TO_LABEL.get(role_name, role_name),
                "user_ids": [u["id"] for u in users],
                "users": users,
            })
    return out
