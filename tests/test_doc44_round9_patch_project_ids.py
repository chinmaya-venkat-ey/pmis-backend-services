"""Doc 44 round 9 — PATCH /users/{id} accepts ``projectIds``.

Round-9 alignment: pre-round-9 PATCH /users/{id} only edited user
fields (name, email, vendor, division, status). Project mappings
required hitting the per-user role-assignments endpoints separately,
even though CREATE accepted ``projectIds`` and GET returned
``projects[]`` / ``projectAssignments[]``. Round 9 closes that gap.

Semantics:
  * ``None`` (omitted)  → no-op
  * ``[]``              → clear project memberships + project-tier role rows
  * ``[p1, p2]``        → replace
"""
from uuid import uuid4

from app.core.security import create_access_token, hash_password
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.project_member import ProjectMemberModel
from app.infrastructure.db.models.role import RoleModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)


def _make_user(db_session, login):
    u = UserModel(
        login=f"{login}-{uuid4().hex[:6]}",
        email=f"{login}-{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pmis@1234"),
        first_name="T", last_name="User",
        status="active", two_factor_enabled=False,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _make_project(db_session, name=None):
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"PR-{uuid4().hex[:8].upper()}",
        name=name or f"P-{uuid4().hex[:5]}",
        status="published",
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _grant(db_session, user, role_name, project_id=None):
    role_id = (
        db_session.query(RoleModel).filter(RoleModel.name == role_name).one().id
    )
    db_session.add(UserRoleAssignmentModel(
        user_id=user.id, role_id=role_id, project_id=project_id,
    ))
    db_session.commit()


class TestPatchProjectIdsReplacement:
    def test_omitting_project_ids_leaves_mappings_unchanged(
        self, client, admin_user, admin_headers, db_session,
    ):
        u = _make_user(db_session, "pa-omit")
        p = _make_project(db_session)
        _grant(db_session, u, "project_member", project_id=p.id)
        db_session.add(ProjectMemberModel(
            project_id=p.id, user_id=u.id, roles=[],
        ))
        db_session.commit()

        resp = client.patch(
            f"/api/v3/users/{u.id}",
            json={"firstName": "Omit"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

        # Existing membership + role row preserved.
        rows = (
            db_session.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.user_id == u.id)
            .all()
        )
        assert len(rows) == 1 and rows[0].project_id == p.id

    def test_empty_project_ids_clears_mappings(
        self, client, admin_user, admin_headers, db_session,
    ):
        u = _make_user(db_session, "pa-clear")
        p = _make_project(db_session)
        _grant(db_session, u, "project_member", project_id=p.id)
        db_session.add(ProjectMemberModel(
            project_id=p.id, user_id=u.id, roles=[],
        ))
        db_session.commit()

        resp = client.patch(
            f"/api/v3/users/{u.id}",
            json={"projectIds": []},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

        # Both rows gone.
        ura_count = (
            db_session.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.user_id == u.id)
            .filter(UserRoleAssignmentModel.project_id.isnot(None))
            .count()
        )
        pm_count = (
            db_session.query(ProjectMemberModel)
            .filter(ProjectMemberModel.user_id == u.id)
            .count()
        )
        assert ura_count == 0
        assert pm_count == 0

    def test_replacement_diff(
        self, client, admin_user, admin_headers, db_session,
    ):
        """Existing rows for projects not in the new list are revoked;
        new rows are granted using the user's existing project-tier
        role (project_member here)."""
        u = _make_user(db_session, "pa-diff")
        p_keep = _make_project(db_session, "keep")
        p_drop = _make_project(db_session, "drop")
        p_add = _make_project(db_session, "add")
        _grant(db_session, u, "project_member", project_id=p_keep.id)
        _grant(db_session, u, "project_member", project_id=p_drop.id)
        for p in (p_keep, p_drop):
            db_session.add(ProjectMemberModel(
                project_id=p.id, user_id=u.id, roles=[],
            ))
        db_session.commit()

        resp = client.patch(
            f"/api/v3/users/{u.id}",
            json={"projectIds": [p_keep.id, p_add.id]},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

        # Final: keep + add. drop is gone.
        rows = (
            db_session.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.user_id == u.id)
            .filter(UserRoleAssignmentModel.project_id.isnot(None))
            .all()
        )
        pids = {r.project_id for r in rows}
        assert pids == {p_keep.id, p_add.id}

        member_pids = {
            r.project_id for r in
            db_session.query(ProjectMemberModel)
            .filter(ProjectMemberModel.user_id == u.id)
            .all()
        }
        assert member_pids == {p_keep.id, p_add.id}

    def test_unknown_project_id_returns_422(
        self, client, admin_user, admin_headers, db_session,
    ):
        u = _make_user(db_session, "pa-bogus")
        bogus = str(uuid4())
        resp = client.patch(
            f"/api/v3/users/{u.id}",
            json={"projectIds": [bogus]},
            headers=admin_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "not found" in resp.text.lower()

    def test_response_carries_updated_projects_array(
        self, client, admin_user, admin_headers, db_session,
    ):
        u = _make_user(db_session, "pa-shape")
        p1 = _make_project(db_session, "p-shape-1")
        p2 = _make_project(db_session, "p-shape-2")
        _grant(db_session, u, "project_member", project_id=p1.id)
        db_session.add(ProjectMemberModel(
            project_id=p1.id, user_id=u.id, roles=[],
        ))
        db_session.commit()

        resp = client.patch(
            f"/api/v3/users/{u.id}",
            json={"projectIds": [p1.id, p2.id]},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert {p["id"] for p in body["projects"]} == {p1.id, p2.id}
