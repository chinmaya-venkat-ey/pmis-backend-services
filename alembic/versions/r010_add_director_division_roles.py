"""Add director_admin / division_owner / division_approver roles and
redefine the permission grants on division_member to match the team's
Master_Data.xlsx specification.

Revision ID: r010_add_director_division_roles
Revises: r009_seed_ungated_patch_fields
Create Date: 2026-06-02

Per Master_Data.xlsx + team decision 2026-06-02, the four new/redefined
UIDAI-tier roles differ as a strict subset hierarchy:

  * `director_admin` (NEW, 22 codes) — read-only system-wide. View any
    project / milestone / activity / task / subtask / comment / user /
    master-data row. No create/edit/delete/publish anywhere. Approval
    inbox detail / approve / reject NOT permitted (no approvals:moderate
    and no division-reviewer role wiring).
  * `division_owner` (NEW, 111 codes) — full operational tier scoped to
    a UIDAI division. Project/milestone/activity/task/subtask CRUD +
    every field-write + user:create + project_members:update +
    rbac:assign (can grant division-tier roles via the role-assignment
    API, per matrix R84 ✓) + approvals:moderate (can moderate any
    approval request in the system).
  * `division_approver` (NEW, 110 codes) — division_owner MINUS
    `rbac:assign`. Cannot grant roles via /role-assignments/* endpoints;
    can still manage project team membership via the
    `project_members:update`-gated bulk-replace endpoint. Retains
    approvals:moderate per team's "broader perms for now" decision.
  * `division_member` (EXISTING — REDEFINED, 109 codes) —
    division_approver MINUS `approvals:moderate`. Cannot moderate
    cross-division approval requests; CAN still approve requests in
    their own division through the existing division-reviewer path
    (concerned_division / activity_owner). The previous 18-code
    read-only observer set is replaced wholesale. Zero users were
    assigned to this role on the server at decision time.

`comments:moderate` is deliberately withheld from all 4 new/redefined
roles — per sheet R53/R58, comments are permanent (no role grants
delete-comment). admin/super_admin retain the code per the 2026-06-02
audit decision to preserve admin's delete-comment authority.

Also in this migration, the `admin` role is narrowed to differ from
`super_admin` per Master_Data.xlsx (R87 + R98). 14 master-data /
RBAC-catalog management codes are revoked from admin so super_admin is
the sole holder. Closes audit gaps §3.6 (notification_templates:manage
phishing vector), §3.9 (permissions:manage code-minting elevation), and
takeover vectors D1 / D2 / D3 / D6 / D7. After r010:

    super_admin: 141 codes  (catalog minus users:grant_superadmin)
    admin:       127 codes  (super_admin minus the 14 narrowing codes)

Per A19, real downgrade implemented (restores the prior 18-code
read-only set on `division_member`, deletes the 3 new role rows, and
re-grants the 14 narrowing codes to admin).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r010_add_director_division_roles"
down_revision: str = "r009_seed_ungated_patch_fields"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Code lists
# ---------------------------------------------------------------------------

_READ_ONLY_CODES = (
    # Project domain reads
    "projects:read", "projects:read_all",
    "milestones:read",
    "activities:read",
    "tasks:read",
    "subtasks:read",
    "comments:read",
    "project_members:read",
    # User domain reads
    "users:read", "users:read_all",
    # RBAC catalog reads
    "permissions:read",
    "roles:read",
    # Masters reads
    "divisions:read",
    "vendors:read",
    "resource_types:read",
    "priorities:read",
    "project_categories:read",
    "activity_types:read",
    "activity_statuses:read",
    "milestone_statuses:read",
    "project_status_transitions:read",
    "notification_templates:read",
)

# Project field-level writes (every PROJECT_FIELD_CODES value, deduped).
_PROJECT_FIELD_WRITES = (
    "projects:update:name",
    "projects:update:description",
    "projects:update:public",
    "projects:update:status_explanation",
    "projects:update:owner",
    "projects:update:owner_other",
    "projects:update:start_date",
    "projects:update:end_date",
    "projects:update:actual_start_date",
    "projects:update:actual_end_date",
    "projects:update:finance",  # 1 code covers totalProjectValueExclTax + taxPercent + ccnCapPercent
    "projects:update:vendors",
    "projects:update:active",
    "projects:update:parent_id",
    "projects:update:status",
)

_MILESTONE_FIELD_WRITES = (
    "milestones:update:name",
    "milestones:update:description",
    "milestones:update:start_date",
    "milestones:update:end_date",
    "milestones:update:actual_start_date",
    "milestones:update:actual_end_date",
    "milestones:update:status",
    "milestones:update:priority",
    "milestones:update:position",
    "milestones:update:dependencies",
    "milestones:update:vendors",
)

_ACTIVITY_FIELD_WRITES = (
    "activities:update:name",
    "activities:update:description",
    "activities:update:start_date",
    "activities:update:end_date",
    "activities:update:actual_start_date",
    "activities:update:actual_end_date",
    "activities:update:status",
    "activities:update:priority",
    "activities:update:position",
    "activities:update:owner_division",
    "activities:update:concerned_divisions",
    "activities:update:vendor_id",
    "activities:update:activity_started",
    "activities:update:category",
    "activities:update:ccn_value",
    "activities:update:owner_division_other",
    "activities:update:concerned_division_other",
    "activities:update:dependencies",
)

_TASK_FIELD_WRITES = (
    "tasks:update:name",
    "tasks:update:description",
    "tasks:update:start_date",
    "tasks:update:end_date",
    "tasks:update:actual_start_date",
    "tasks:update:actual_end_date",
    "tasks:update:status",
    "tasks:update:priority",
    "tasks:update:position",
    "tasks:update:assigned_to",
    "tasks:update:dependencies",
)

_SUBTASK_FIELD_WRITES = (
    "subtasks:update:name",
    "subtasks:update:description",
    "subtasks:update:start_date",
    "subtasks:update:end_date",
    "subtasks:update:actual_start_date",
    "subtasks:update:actual_end_date",
    "subtasks:update:status",
    "subtasks:update:priority",
    "subtasks:update:position",
    "subtasks:update:assigned_to",
    "subtasks:update:dependencies",
)

# Operational action codes shared by division_owner / approver / member.
# `comments:moderate` is intentionally excluded — sheet R53/R58 forbids
# delete-comment for every role. admin/super_admin retain the code via
# r005/r008 per the 2026-06-02 audit's preservation decision.
_OPERATIONAL_ACTION_CODES = (
    "projects:create", "projects:delete_all",
    "projects:publish", "projects:close", "projects:reopen",
    "milestones:create", "milestones:delete", "milestones:restore",
    "activities:create", "activities:delete", "activities:restore",
    "tasks:create", "tasks:delete", "tasks:restore",
    "subtasks:create", "subtasks:delete", "subtasks:restore",
    "comments:create",
    "attachments:create",
    "approvals:moderate",
    "project_members:update",
    "users:create",
)

# director_admin: pure read tier.
DIRECTOR_ADMIN_CODES = tuple(dict.fromkeys(_READ_ONLY_CODES))

# division_owner: reads + every operational action + every field-write +
# rbac:assign so they can grant division-tier roles within their scope.
DIVISION_OWNER_CODES = tuple(dict.fromkeys(
    _READ_ONLY_CODES
    + _OPERATIONAL_ACTION_CODES
    + _PROJECT_FIELD_WRITES
    + _MILESTONE_FIELD_WRITES
    + _ACTIVITY_FIELD_WRITES
    + _TASK_FIELD_WRITES
    + _SUBTASK_FIELD_WRITES
    + ("rbac:assign",)
))

# division_approver: division_owner MINUS rbac:assign. Cannot grant roles
# via /role-assignments/* endpoints. Can still manage team via
# project_members:update bulk-replace. Retains approvals:moderate per
# team's "broader for now" decision.
DIVISION_APPROVER_CODES = tuple(c for c in DIVISION_OWNER_CODES if c != "rbac:assign")

# division_member: division_approver MINUS approvals:moderate. Cannot
# moderate cross-division approval requests. Still approves requests in
# their own division through the division-reviewer path (the service-
# layer _authorize_detail accepts concerned_division / activity_owner
# roles in addition to the moderate code).
DIVISION_MEMBER_NEW_CODES = tuple(
    c for c in DIVISION_APPROVER_CODES if c != "approvals:moderate"
)

# Codes admin currently holds (via r005) that per Master_Data.xlsx should
# be super_admin-only. Revoked from admin in upgrade(); re-granted in
# downgrade(). Master-data catalog management (R87 + R98) + RBAC catalog
# management (permissions:manage, roles:create/update/delete).
ADMIN_NARROWING_CODES = (
    # Master-data catalog "manage" codes — sheet R87 says "Only Super
    # Admin can fully manage the catalog."
    "divisions:manage",
    "vendors:manage",
    "resource_types:manage",
    "priorities:manage",
    "project_categories:manage",
    "activity_types:manage",
    "activity_statuses:manage",
    "milestone_statuses:manage",
    "project_status_transitions:manage",
    "notification_templates:manage",
    # RBAC catalog management — admin shouldn't mint codes or redefine
    # role rows. Sheet R98 "Others" lists these without granting them.
    "permissions:manage",
    "roles:create",
    "roles:update",
    "roles:delete",
)

# division_member: previous 18-code observer set (restored on downgrade).
DIVISION_MEMBER_LEGACY_CODES = (
    "projects:read",
    "milestones:read",
    "activities:read",
    "tasks:read",
    "subtasks:read",
    "comments:read",
    "users:read",
    "divisions:read",
    "vendors:read",
    "resource_types:read",
    "priorities:read",
    "project_categories:read",
    "activity_types:read",
    "activity_statuses:read",
    "milestone_statuses:read",
    "project_status_transitions:read",
    "notification_templates:read",
    "project_members:read",
)


def _ensure_role(bind, name: str, description: str) -> int:
    """Insert a role row if absent; return its id."""
    row = bind.execute(sa.text(
        "SELECT id FROM users.roles WHERE name = :name"
    ), {"name": name}).first()
    if row:
        return row[0]
    bind.execute(sa.text("""
        INSERT INTO users.roles (name, description, builtin, created_at)
        VALUES (:name, :desc, true, NOW())
    """), {"name": name, "desc": description})
    return bind.execute(sa.text(
        "SELECT id FROM users.roles WHERE name = :name"
    ), {"name": name}).first()[0]


def _grant_codes(bind, role_id: int, codes) -> None:
    for code in codes:
        bind.execute(sa.text("""
            INSERT INTO users.role_permissions (role_id, permission_code)
            VALUES (:rid, :code)
            ON CONFLICT (role_id, permission_code) DO NOTHING
        """), {"rid": role_id, "code": code})


def upgrade() -> None:
    bind = op.get_bind()

    # ---- 1. Create the three new role rows ----
    director_id = _ensure_role(
        bind, "director_admin",
        "Director Admin — read-only access across the entire system "
        "(UIDAI tier).",
    )
    div_owner_id = _ensure_role(
        bind, "division_owner",
        "Division Owner — full operational tier scoped to a UIDAI "
        "division; can assign division-tier roles within scope.",
    )
    div_approver_id = _ensure_role(
        bind, "division_approver",
        "Division Approver — full operational tier scoped to a UIDAI "
        "division; broader-than-strict grants per team decision 2026-06-02.",
    )

    # ---- 2. Grant code sets ----
    _grant_codes(bind, director_id, DIRECTOR_ADMIN_CODES)
    _grant_codes(bind, div_owner_id, DIVISION_OWNER_CODES)
    _grant_codes(bind, div_approver_id, DIVISION_APPROVER_CODES)

    # ---- 3. Redefine division_member ----
    # Wipe the old read-only grants then apply the new operational set.
    div_member_row = bind.execute(sa.text(
        "SELECT id FROM users.roles WHERE name = 'division_member'"
    )).first()
    if div_member_row:
        div_member_id = div_member_row[0]
        bind.execute(sa.text(
            "DELETE FROM users.role_permissions WHERE role_id = :rid"
        ), {"rid": div_member_id})
        _grant_codes(bind, div_member_id, DIVISION_MEMBER_NEW_CODES)

    # ---- 4. Narrow admin to differ from super_admin ----
    # Revoke the 14 master-data / RBAC-catalog management codes so
    # super_admin is the sole holder. Targets admin specifically by
    # joining on role name; super_admin grants are untouched.
    admin_row = bind.execute(sa.text(
        "SELECT id FROM users.roles WHERE name = 'admin'"
    )).first()
    if admin_row:
        admin_id = admin_row[0]
        bind.execute(sa.text("""
            DELETE FROM users.role_permissions
            WHERE role_id = :rid
              AND permission_code = ANY(:codes)
        """), {"rid": admin_id, "codes": list(ADMIN_NARROWING_CODES)})


def downgrade() -> None:
    """Restore the prior 18-code observer grant set on division_member,
    delete the three new role rows, and re-grant the 14 narrowing codes
    to admin. Idempotent."""
    bind = op.get_bind()

    # ---- 0. Re-grant the narrowing codes to admin ----
    admin_row = bind.execute(sa.text(
        "SELECT id FROM users.roles WHERE name = 'admin'"
    )).first()
    if admin_row:
        _grant_codes(bind, admin_row[0], ADMIN_NARROWING_CODES)

    # ---- 1. Restore division_member's legacy grants ----
    div_member_row = bind.execute(sa.text(
        "SELECT id FROM users.roles WHERE name = 'division_member'"
    )).first()
    if div_member_row:
        div_member_id = div_member_row[0]
        bind.execute(sa.text(
            "DELETE FROM users.role_permissions WHERE role_id = :rid"
        ), {"rid": div_member_id})
        _grant_codes(bind, div_member_id, DIVISION_MEMBER_LEGACY_CODES)

    # ---- 2. Delete the three new roles + their grants ----
    for name in ("division_approver", "division_owner", "director_admin"):
        row = bind.execute(sa.text(
            "SELECT id FROM users.roles WHERE name = :n"
        ), {"n": name}).first()
        if not row:
            continue
        rid = row[0]
        # Drop dependent rows first (no FK CASCADE assumed).
        bind.execute(sa.text(
            "DELETE FROM users.role_permissions WHERE role_id = :rid"
        ), {"rid": rid})
        bind.execute(sa.text(
            "DELETE FROM users.user_role_assignments WHERE role_id = :rid"
        ), {"rid": rid})
        bind.execute(sa.text(
            "DELETE FROM users.user_roles WHERE role_id = :rid"
        ), {"rid": rid})
        bind.execute(sa.text(
            "DELETE FROM users.roles WHERE id = :rid"
        ), {"rid": rid})
