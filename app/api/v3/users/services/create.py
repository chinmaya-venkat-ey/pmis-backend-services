"""
User creation service.

Single transaction:
  1. Validate inputs (login, email, password, division catalog membership,
     division_other when division == 'others').
  2. Verify the supplied vendor exists and is not soft-deleted.
  3. Verify each project_id references an existing non-deleted project.
  4. Insert the user row + project_members rows.
  5. Commit.

Doc 49: ``division`` membership is validated against the shared
``divisions`` master table (owned by monolith, read here via raw SQL).
Built-ins (tmd1/tmd2/others) are seeded by monolith's init_db so they
pass; admin-added codes pass; soft-disabled rows do not.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from .....core.security import hash_password
from .....domain.resource_types.resource_type import DIVISION_OTHERS
from .....domain.users.user import User
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from .....infrastructure.db.models.role import RoleModel as _PMRole
from .....infrastructure.db.models.vendor import VendorModel
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....infrastructure.db.repositories.vendor_repository import VendorRepository
from .....shared.division_catalog import is_known_active_division
from .....shared.service_result import ServiceResult
from .....shared.utils import (
    is_valid_email,
    is_valid_login,
    is_valid_password,
    normalize_email,
    normalize_login,
    normalize_string,
)


_ORG_ROLE_VALUES: tuple[str, ...] = (
    "super_admin",
    "admin",
    "org_admin",
    "project_admin",
    "project_member",
    # ``division_member`` is NOT in the FE's enum but the BE supports
    # it; allow it for completeness (callers driving by API directly
    # may want to set it). Excluded from orgRole projection so the FE
    # doesn't have to recognise it.
    "division_member",
)

# Reverse map from human-readable display labels (the FE ships
# "Project Admin" / "Project Member" in projectAssignments[].role) back
# to canonical role names. We accept either form here so the FE can
# send whichever it has on hand.
_ROLE_LABEL_TO_NAME: dict = {
    "super admin":      "super_admin",
    "admin":            "admin",
    "organization admin": "org_admin",
    "org admin":        "org_admin",
    "project admin":    "project_admin",
    "project member":   "project_member",
    "division member":  "division_member",
}


def _normalize_role_name(raw: Optional[str]) -> Optional[str]:
    """Accept either the canonical role name (``project_admin``) or
    the FE display label (``"Project Admin"``) and return the canonical
    form. Empty / None inputs return None."""
    if not raw:
        return None
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    if cleaned in _ORG_ROLE_VALUES:
        return cleaned
    return _ROLE_LABEL_TO_NAME.get(cleaned.lower())


def _resolve_project_role_for(
    org_role: Optional[str], assignment_role: Optional[str],
) -> Optional[str]:
    """Decide the per-project role for an assignment row.

    Precedence: an explicit per-project role (from
    ``projectAssignments``) wins over the user's primary ``orgRole``.
    Returns None when the result isn't a project-tier role (admin /
    super_admin / org_admin) — those scopes are handled separately."""
    explicit = _normalize_role_name(assignment_role)
    if explicit and explicit in {"project_admin", "project_member", "division_member"}:
        return explicit
    if org_role in {"project_admin", "project_member", "division_member"}:
        return org_role
    return None


def create_user(
    db: Session,
    login: str,
    email: str,
    password: str,
    *,
    vendor_id: str,
    division: str,
    phone_number: str,
    division_other: Optional[str] = None,
    project_ids: Optional[List[str]] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    admin: bool = False,
    org_role: Optional[str] = None,
    project_assignments: Optional[List[dict]] = None,
    caller_id: Optional[str] = None,
) -> ServiceResult[User]:
    """
    Create a new user and its project mappings.

    Doc 44: when ``org_role`` is supplied, the service ALSO writes the
    matching role-assignment row(s) inside the same transaction. The
    caller-vs-target gate (``can_caller_grant``) is consulted before
    each insert; on any rejection the entire create is rolled back.

    All required-field semantics are enforced here so callers (the API
    controller) don't have to repeat them.
    """
    # ---- Normalize ------------------------------------------------------
    login = normalize_login(login)
    email = normalize_email(email)
    division = (division or "").strip().lower()
    division_other = (
        normalize_string(division_other) if division_other is not None else None
    )

    # ---- Format validation ----------------------------------------------
    if not is_valid_login(login):
        return ServiceResult.fail(
            error="Invalid login format. Must be 3-50 alphanumeric characters, underscores, or hyphens.",
            error_type="validation_error",
        )
    if not is_valid_email(email):
        return ServiceResult.fail(
            error="Invalid email format",
            error_type="validation_error",
        )
    if not is_valid_password(password):
        return ServiceResult.fail(
            error="Password must be at least 8 characters long",
            error_type="validation_error",
        )

    # ---- Division ------------------------------------------------------
    # Doc 49: must be an active row in the shared ``divisions`` master
    # table. Built-ins (tmd1/tmd2/others) are seeded by monolith init_db.
    if not is_known_active_division(db, division):
        return ServiceResult.fail(
            error=(
                f"division '{division}' is not an active division. "
                f"Pick one from GET /api/v3/master/divisions."
            ),
            error_type="validation_error",
        )
    if division == DIVISION_OTHERS:
        if not division_other:
            return ServiceResult.fail(
                error="divisionOther is required when division is 'others'.",
                error_type="validation_error",
            )
    else:
        if division_other:
            return ServiceResult.fail(
                error="divisionOther may only be provided when division is 'others'.",
                error_type="validation_error",
            )
        division_other = None

    # ---- Phone number (required) ---------------------------------------
    # Schema already enforces non-empty + max 50; this guard catches the
    # direct-service-call path (CLI / internal scripts) that bypasses the
    # Pydantic layer. Mirrors the vendor_id guard below.
    phone_number = (phone_number or "").strip()
    if not phone_number:
        return ServiceResult.fail(
            error="phoneNumber is required.",
            error_type="validation_error",
        )
    if len(phone_number) > 50:
        return ServiceResult.fail(
            error="phoneNumber must be 1-50 characters.",
            error_type="validation_error",
        )

    # ---- Vendor --------------------------------------------------------
    # Doc 25: ``vendor_id`` accepts either a UUID or a ``VN-...`` code.
    # We resolve to the canonical UUID first (None on unresolvable),
    # then verify the underlying row exists and is live.
    if not vendor_id:
        return ServiceResult.fail(
            error="vendorId is required.",
            error_type="validation_error",
        )
    canonical_vendor_id = VendorRepository(db).resolve_id(vendor_id)
    vendor = None
    if canonical_vendor_id:
        vendor = (
            db.query(VendorModel)
            .filter(VendorModel.id == canonical_vendor_id)
            .filter(VendorModel.deleted_at.is_(None))
            .first()
        )
    if vendor is None:
        return ServiceResult.fail(
            error=f"Vendor '{vendor_id}' not found or has been deleted.",
            error_type="validation_error",
            details={"field": "vendorId", "value": vendor_id},
        )
    # Pin to the canonical UUID so the inserted row holds the immutable
    # FK regardless of whether the caller sent a UUID or a code.
    vendor_id = canonical_vendor_id

    # ---- Project mapping ------------------------------------------------
    project_ids = list(dict.fromkeys(project_ids or []))  # de-dupe, preserve order
    normalized_org_role = _normalize_role_name(org_role)
    if org_role is not None and normalized_org_role is None:
        return ServiceResult.fail(
            error=(
                f"Invalid orgRole '{org_role}'. Must be one of: "
                f"{', '.join(_ORG_ROLE_VALUES)}."
            ),
            error_type="validation_error",
        )
    # Doc 44 round 3: project mapping is optional for ALL orgRoles
    # (and for the legacy no-orgRole path). The FE form shows project
    # mapping for every role but doesn't require it — operators can
    # create a user and assign projects later via /role-assignments.
    # Empty project_ids → no project_members rows AND no project-scoped
    # role-assignment rows. The user's orgRole projection in the
    # response will reflect whatever role rows did get written (e.g.
    # for org_admin the org-scoped row is still written; for project-
    # tier orgRoles with no projects, no row is written and the
    # response's orgRole comes back null until projects are assigned).
    if project_ids:
        found_ids = {
            pid
            for (pid,) in db.query(ProjectModel.id)
            .filter(ProjectModel.id.in_(project_ids))
            .filter(ProjectModel.deleted_at.is_(None))
            .all()
        }
        missing = [p for p in project_ids if p not in found_ids]
        if missing:
            return ServiceResult.fail(
                error=f"Project(s) not found or deleted: {', '.join(missing)}",
                error_type="validation_error",
                details={"field": "projectIds", "missing": missing},
            )

    # ---- Uniqueness checks ---------------------------------------------
    repository = UserRepository(db)
    if repository.exists_by_login(login):
        return ServiceResult.fail(
            error=f"User with login '{login}' already exists",
            error_type="already_exists",
        )
    if repository.exists_by_email(email):
        return ServiceResult.fail(
            error=f"User with email '{email}' already exists",
            error_type="already_exists",
        )

    # ---- Doc 44: plan + pre-authorize role assignments -----------------
    # We compute the (role_name, org_id, project_id) tuples we'll insert
    # and run the caller-vs-target gate against EACH of them BEFORE
    # writing the user, so we don't end up with an orphan user when
    # the caller isn't authorized for the requested orgRole.
    planned_assignments: List[tuple] = []
    if normalized_org_role:
        # Merge projectAssignments + assignments — the FE form sends
        # both fields with the same shape; honour entries from either.
        explicit_role_by_pid: dict = {}
        for entry in (project_assignments or []):
            pid = entry.get("projectId")
            if pid:
                # First non-empty role wins; later non-empty values
                # don't overwrite (FE redundancy is informational).
                existing = explicit_role_by_pid.get(pid)
                role_label = entry.get("role")
                if not existing and role_label:
                    explicit_role_by_pid[pid] = role_label

        if normalized_org_role in {"super_admin", "admin"}:
            planned_assignments.append((normalized_org_role, None, None))
        elif normalized_org_role == "org_admin":
            # Org-scoped: bind to the user's vendor.
            planned_assignments.append((normalized_org_role, vendor_id, None))
        else:
            # Project-tier orgRoles (project_admin / project_member /
            # division_member). One assignment row per project_id.
            # When projectAssignments carries an explicit role label
            # for a project, that overrides the orgRole default — this
            # supports the FE's "project_admin who is project_member on
            # some of their projects" case (orgRole=project_admin,
            # projectAssignments[].role="Project Member" for some).
            if not project_ids:
                # project_member without project_ids is allowed (user
                # exists but isn't yet attached to projects). Fine — no
                # assignments planned in that case.
                pass
            for pid in project_ids:
                role_for_pid = _resolve_project_role_for(
                    normalized_org_role,
                    explicit_role_by_pid.get(pid),
                )
                if not role_for_pid:
                    return ServiceResult.fail(
                        error=(
                            f"Could not determine project role for {pid}. "
                            "Provide a role in projectAssignments[] or "
                            "use a project-tier orgRole."
                        ),
                        error_type="validation_error",
                    )
                planned_assignments.append((role_for_pid, None, pid))

    # Caller-vs-target check for every planned tuple.
    if planned_assignments and caller_id:
        from ...role_assignments.services import can_caller_grant
        for (role_name, org_id, project_id) in planned_assignments:
            allowed, reason = can_caller_grant(
                db, caller_id,
                target_role_name=role_name,
                target_organization_id=org_id,
                target_project_id=project_id,
            )
            if not allowed:
                return ServiceResult.fail(
                    error=reason or (
                        f"Caller is not authorized to grant '{role_name}'."
                    ),
                    error_type="authorization_error",
                )

    # ---- Persist --------------------------------------------------------
    try:
        # Doc 44: when the caller asked for orgRole=admin/super_admin,
        # also flip the legacy ``admin`` boolean on the user row so old
        # is_admin checks still work. (super_admin counts as admin via
        # the union check at auth time, but the user row's flag is what
        # the legacy code reads; keep them consistent.)
        effective_admin_flag = admin
        if normalized_org_role in {"admin", "super_admin"}:
            effective_admin_flag = True

        user = repository.create(
            login=login,
            email=email,
            hashed_password=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            admin=effective_admin_flag,
            vendor_id=vendor_id,
            division=division,
            division_other=division_other,
            phone_number=phone_number,
            # Doc 45 round 9b: persist the FE's intended orgRole tier on
            # the user row. ``derive_org_role`` falls back to this column
            # when no role-assignment row exists — closes the
            # project-tier + empty-project_ids gap where the previous
            # behaviour silently dropped the orgRole label.
            org_role=normalized_org_role,
        )

        # Wire up project membership via the scoped-RBAC table.
        # ``roles`` on the legacy project_members table was always
        # written as [] — each row maps to a single URA row with
        # role=project_member, project_id set, organization_id NULL.
        if project_ids:
            pm_role_id = (
                db.query(_PMRole.id)
                .filter(_PMRole.name == "project_member")
                .scalar()
            )
            if pm_role_id is None:
                raise RuntimeError(
                    "project_member role not seeded — RBAC sync did not run"
                )
            for pid in project_ids:
                db.add(UserRoleAssignmentModel(
                    user_id=user.id,
                    role_id=pm_role_id,
                    project_id=pid,
                ))
        db.flush()

        # Doc 44 — write the planned role assignments. The repo helper
        # is idempotent on (user, role, scope), so a re-run of the same
        # request returns existing rows without duplicating.
        if planned_assignments:
            from .....infrastructure.db.models.role import RoleModel as _Role
            from .....infrastructure.db.repositories.rbac_repository import (
                RbacRepository,
            )
            rbac = RbacRepository(db)
            wanted_role_names = {a[0] for a in planned_assignments}
            role_id_by_name = {
                r.name: r.id
                for r in db.query(_Role)
                .filter(_Role.name.in_(wanted_role_names))
                .all()
            }
            missing_roles = wanted_role_names - role_id_by_name.keys()
            if missing_roles:
                # Should not happen on a healthy DB — every role above
                # is one of the seeded built-ins. Treat as internal.
                raise RuntimeError(
                    f"Role(s) not found in DB: {sorted(missing_roles)}"
                )
            for (role_name, org_id, project_id) in planned_assignments:
                rbac.assign_scoped_role(
                    user_id=user.id,
                    role_id=role_id_by_name[role_name],
                    organization_id=org_id,
                    project_id=project_id,
                    actor_id=caller_id,
                )
            db.flush()

        # Hydrate the response with the just-mapped projects.
        # Re-fetch via repo so the projects array reflects the live DB
        # (filters closed/soft-deleted).
        hydrated = repository.get_by_id(user.id)
        db.commit()
        return ServiceResult.ok(hydrated or user)

    except Exception as e:  # noqa: BLE001
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to create user: {e}",
            error_type="internal_error",
        )
