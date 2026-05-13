"""Doc 53 — assignee narrowing on tasks / subtasks for non-admin callers
(mirror of monolith 80ecb1f).

When the caller is ``project_admin``, ``project_member``, or
``org_admin``, the assignee must:
  1. Be in the same vendor as the caller (``users.vendor_id`` match).
  2. Hold a project-tier role assignment on the target project.

``admin`` / ``super_admin`` callers bypass both narrowing checks.

These tests target the validator directly so the rule is covered in
isolation; the existing ``test_assigned_to_on_ts.py`` continues to
exercise the end-to-end task/subtask flows under the admin fixture and
all still pass after this change.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.errors import ValidationError
from app.core.security import hash_password
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from app.infrastructure.db.models.vendor import VendorModel
from app.shared.assignee import validate_assignable_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vendor(db, *, name="Acme") -> VendorModel:
    v = VendorModel(
        id=str(uuid4()),
        vendor_code=f"VN-{uuid4().hex[:6].upper()}",
        name=name, active=True,
        phone_number="+919999999999",
        email=f"ops_{uuid4().hex[:6]}@acme.example",
    )
    db.add(v); db.commit(); db.refresh(v)
    return v


def _user(db, *, login_prefix, vendor=None, status="active") -> UserModel:
    u = UserModel(
        login=f"{login_prefix}_{uuid4().hex[:6]}",
        email=f"{login_prefix}_{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("x"),
        first_name=login_prefix.capitalize(),
        last_name="User",
        status=status,
        two_factor_enabled=False,
        vendor_id=(vendor.id if vendor else None),
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _role(db, name) -> RoleModel:
    existing = db.query(RoleModel).filter_by(name=name).first()
    if existing:
        return existing
    r = RoleModel(name=name)
    db.add(r); db.commit(); db.refresh(r)
    return r


def _assign(db, user, role, *, project_id=None, organization_id=None):
    a = UserRoleAssignmentModel(
        user_id=user.id, role_id=role.id,
        project_id=project_id, organization_id=organization_id,
    )
    db.add(a); db.commit()
    return a


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project(db_session):
    """A minimal project row — the validator only needs the id."""
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"UIDAI-PR{uuid4().hex[:14].upper()}",
        name=f"P-{uuid4().hex[:6]}",
        description="-",
        active=True, public=False, status="new",
        owner="tmd1",
        start_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    db_session.add(p); db_session.commit()
    return p


@pytest.fixture
def vendor_a(db_session):
    return _vendor(db_session, name="Vendor A")


@pytest.fixture
def vendor_b(db_session):
    return _vendor(db_session, name="Vendor B")


@pytest.fixture
def roles(db_session):
    return {
        "project_admin": _role(db_session, "project_admin"),
        "project_member": _role(db_session, "project_member"),
        "division_member": _role(db_session, "division_member"),
        "org_admin": _role(db_session, "org_admin"),
        "admin": _role(db_session, "admin"),
        "super_admin": _role(db_session, "super_admin"),
    }


# ---------------------------------------------------------------------------
# 1. Back-compat — without the new kwargs, behaviour is unchanged
# ---------------------------------------------------------------------------

class TestBackCompat:
    def test_legacy_call_only_checks_active_not_deleted(self, db_session, vendor_a):
        u = _user(db_session, login_prefix="alice", vendor=vendor_a)
        # Legacy two-arg form: no project_id, no caller_user_id.
        # Should NOT trigger the new narrowing — only the active/deleted
        # checks run.
        assert validate_assignable_user_id(db_session, u.id) == u.id


# ---------------------------------------------------------------------------
# 2. admin / super_admin bypass — no narrowing applied
# ---------------------------------------------------------------------------

class TestAdminBypass:
    def test_admin_caller_can_assign_anywhere(
        self, db_session, vendor_a, vendor_b, roles, project,
    ):
        # admin caller has no vendor, no project membership.
        admin = _user(db_session, login_prefix="root")
        _assign(db_session, admin, roles["admin"])  # global scope
        # Assignee is in a completely unrelated vendor and not on the
        # project — admin's bypass means it's still allowed.
        target = _user(db_session, login_prefix="random", vendor=vendor_b)
        assert validate_assignable_user_id(
            db_session, target.id,
            project_id=project.id, caller_user_id=admin.id,
        ) == target.id

    def test_super_admin_caller_can_assign_anywhere(
        self, db_session, vendor_b, roles, project,
    ):
        sa = _user(db_session, login_prefix="su")
        _assign(db_session, sa, roles["super_admin"])
        target = _user(db_session, login_prefix="random", vendor=vendor_b)
        assert validate_assignable_user_id(
            db_session, target.id,
            project_id=project.id, caller_user_id=sa.id,
        ) == target.id


# ---------------------------------------------------------------------------
# 3. Narrowing applies to project_admin / project_member / org_admin
# ---------------------------------------------------------------------------

class TestNarrowingHappyPath:
    @pytest.mark.parametrize("caller_role", ["project_admin", "project_member", "org_admin"])
    def test_same_vendor_and_project_member_succeeds(
        self, db_session, vendor_a, roles, project, caller_role,
    ):
        caller = _user(db_session, login_prefix="caller", vendor=vendor_a)
        if caller_role == "org_admin":
            _assign(db_session, caller, roles[caller_role],
                    organization_id=vendor_a.id)
        else:
            _assign(db_session, caller, roles[caller_role],
                    project_id=project.id)
        # Assignee: same vendor, project_member on this project.
        target = _user(db_session, login_prefix="target", vendor=vendor_a)
        _assign(db_session, target, roles["project_member"],
                project_id=project.id)
        assert validate_assignable_user_id(
            db_session, target.id,
            project_id=project.id, caller_user_id=caller.id,
        ) == target.id


class TestNarrowingCrossVendor:
    @pytest.mark.parametrize("caller_role", ["project_admin", "project_member", "org_admin"])
    def test_different_vendor_rejected(
        self, db_session, vendor_a, vendor_b, roles, project, caller_role,
    ):
        caller = _user(db_session, login_prefix="caller", vendor=vendor_a)
        if caller_role == "org_admin":
            _assign(db_session, caller, roles[caller_role],
                    organization_id=vendor_a.id)
        else:
            _assign(db_session, caller, roles[caller_role],
                    project_id=project.id)
        # Assignee is on the project but in a DIFFERENT vendor.
        target = _user(db_session, login_prefix="alien", vendor=vendor_b)
        _assign(db_session, target, roles["project_member"],
                project_id=project.id)
        with pytest.raises(ValidationError) as exc:
            validate_assignable_user_id(
                db_session, target.id,
                project_id=project.id, caller_user_id=caller.id,
            )
        assert "your organization" in str(exc.value)


class TestNarrowingNotOnProject:
    @pytest.mark.parametrize("caller_role", ["project_admin", "project_member", "org_admin"])
    def test_assignee_not_a_project_member_rejected(
        self, db_session, vendor_a, roles, project, caller_role,
    ):
        caller = _user(db_session, login_prefix="caller", vendor=vendor_a)
        if caller_role == "org_admin":
            _assign(db_session, caller, roles[caller_role],
                    organization_id=vendor_a.id)
        else:
            _assign(db_session, caller, roles[caller_role],
                    project_id=project.id)
        # Assignee shares the vendor but has NO project-tier role on
        # the project.
        target = _user(db_session, login_prefix="bystander", vendor=vendor_a)
        with pytest.raises(ValidationError) as exc:
            validate_assignable_user_id(
                db_session, target.id,
                project_id=project.id, caller_user_id=caller.id,
            )
        assert "not assigned to this project" in str(exc.value)


class TestProjectTierAcceptance:
    @pytest.mark.parametrize("assignee_role", ["project_admin", "project_member", "division_member"])
    def test_each_project_tier_role_counts_as_project_member(
        self, db_session, vendor_a, roles, project, assignee_role,
    ):
        # Caller is a project_admin.
        caller = _user(db_session, login_prefix="caller", vendor=vendor_a)
        _assign(db_session, caller, roles["project_admin"],
                project_id=project.id)
        # Assignee holds the parametrised project-tier role on this
        # same project, same vendor.
        target = _user(db_session, login_prefix=assignee_role, vendor=vendor_a)
        _assign(db_session, target, roles[assignee_role],
                project_id=project.id)
        assert validate_assignable_user_id(
            db_session, target.id,
            project_id=project.id, caller_user_id=caller.id,
        ) == target.id


class TestEdgeCases:
    def test_caller_with_no_vendor_binding_rejected(
        self, db_session, vendor_a, roles, project,
    ):
        # A project_admin with no vendor_id on the users row is a data
        # anomaly. The validator should refuse rather than silently
        # let cross-vendor assignments through.
        caller = _user(db_session, login_prefix="orphan", vendor=None)
        _assign(db_session, caller, roles["project_admin"],
                project_id=project.id)
        target = _user(db_session, login_prefix="target", vendor=vendor_a)
        _assign(db_session, target, roles["project_member"],
                project_id=project.id)
        with pytest.raises(ValidationError) as exc:
            validate_assignable_user_id(
                db_session, target.id,
                project_id=project.id, caller_user_id=caller.id,
            )
        assert "vendor binding" in str(exc.value)

    def test_inactive_assignee_still_rejected(
        self, db_session, vendor_a, roles, project,
    ):
        # Layer-1 check still fires even when Layer-2 args are provided.
        caller = _user(db_session, login_prefix="caller", vendor=vendor_a)
        _assign(db_session, caller, roles["project_admin"],
                project_id=project.id)
        target = _user(db_session, login_prefix="dormant", vendor=vendor_a,
                       status="inactive")
        _assign(db_session, target, roles["project_member"],
                project_id=project.id)
        with pytest.raises(ValidationError) as exc:
            validate_assignable_user_id(
                db_session, target.id,
                project_id=project.id, caller_user_id=caller.id,
            )
        assert "is not active" in str(exc.value)
