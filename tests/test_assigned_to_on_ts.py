"""Doc 41 follow-up — optional ``assignedTo`` on tasks / subtasks /
nested subtasks (mirror of the monolith).

Activity (and milestone) deliberately do NOT have an assignee — assignment
lives on tasks and below, where day-to-day owner of work is meaningful.

Coverage:
  * optional on create at T/S/nested (omitted -> null in DB)
  * round-trip when supplied (UUID -> stored, name resolved on read)
  * unknown UUID -> 422
  * inactive user -> 422
  * soft-deleted user -> 422
  * PATCH change assignment
  * PATCH unassign with explicit null (unset semantics)
  * PATCH omit -> assignment unchanged
  * tree response surfaces ``assignedTo`` + ``assignedToName`` on
    T / S / nested-S nodes; M and A do NOT carry the field
  * independence: T's assignee != S's != nested's (no cascade)
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.infrastructure.db.models.user import UserModel


def _iso(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+05:30"


# Admin UUID matches the conftest fixture seed (so JWT.sub resolves to
# this user). See tests/conftest.py:_ADMIN_UUID.
_ADMIN_UUID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Fixtures: an active assignee, an inactive one, and a soft-deleted one
# ---------------------------------------------------------------------------

@pytest.fixture
def alice_user(db_session):
    """A second active user (besides admin) we can assign to."""
    u = UserModel(
        id=str(uuid4()),
        login=f"alice_{uuid4().hex[:6]}",
        email=f"alice_{uuid4().hex[:6]}@example.com",
        hashed_password="not-used-in-project-service-tests",
        first_name="Alice",
        last_name="Wonder",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def inactive_user(db_session):
    u = UserModel(
        id=str(uuid4()),
        login=f"inactive_{uuid4().hex[:6]}",
        email=f"inactive_{uuid4().hex[:6]}@example.com",
        hashed_password="not-used-in-project-service-tests",
        first_name="Ina",
        last_name="Active",
        status="inactive",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def deleted_user(db_session):
    u = UserModel(
        id=str(uuid4()),
        login=f"gone_{uuid4().hex[:6]}",
        email=f"gone_{uuid4().hex[:6]}@example.com",
        hashed_password="not-used-in-project-service-tests",
        first_name="Gone",
        last_name="User",
        status="active",
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


# ---------------------------------------------------------------------------
# Setup helpers — project + vendor + milestone + activity (published)
# ---------------------------------------------------------------------------

def _setup_published_activity(client, admin_headers):
    proj = client.post(
        "/api/v3/projects/create",
        headers=admin_headers,
        json={
            "name": f"Asg P {uuid4().hex[:4]}", "owner": "tmd1",
            "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 12, 31),
        },
    ).json()["data"]
    pid = proj["id"]
    v = client.post(
        "/api/v3/vendors/create",
        headers=admin_headers,
        json={"name": f"Asg V {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
    ).json()["data"]
    vid = v["id"]
    client.patch(
        f"/api/v3/projects/{pid}", headers=admin_headers,
        json={"vendorIds": [vid]},
    )
    m = client.post(
        f"/api/v3/projects/{pid}/milestones/create",
        headers=admin_headers,
        json={
            "name": "M1",
            "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30),
            "priority": "p1",
        },
    ).json()["data"]
    a = client.post(
        f"/api/v3/milestones/{m['id']}/activities/create",
        headers=admin_headers,
        json={
            "name": "A1",
            "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 30),
            "ownerDivision": "tmd1", "vendorId": vid, "concernedDivision": ["tmd1"],
            "priority": "p1",
        },
    ).json()["data"]
    pub = client.post(f"/api/v3/projects/{pid}/publish", headers=admin_headers)
    assert pub.status_code in (200, 201), pub.text
    return pid, vid, m, a


def _make_task(client, headers, aid, *, assigned_to=None, name="T1"):
    body = {
        "name": name,
        "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 15),
        "priority": "p1",
    }
    if assigned_to is not None:
        body["assignedTo"] = assigned_to
    return client.post(
        f"/api/v3/activities/{aid}/tasks/create", headers=headers, json=body,
    )


def _make_subtask(client, headers, tid, *, assigned_to=None, name="S1"):
    body = {
        "name": name,
        "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
        "priority": "p1",
    }
    if assigned_to is not None:
        body["assignedTo"] = assigned_to
    return client.post(
        f"/api/v3/tasks/{tid}/subtasks/create", headers=headers, json=body,
    )


def _make_nested(client, headers, sid, *, assigned_to=None, name="S1.1"):
    body = {
        "name": name,
        "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 5),
        "priority": "p1",
    }
    if assigned_to is not None:
        body["assignedTo"] = assigned_to
    return client.post(
        f"/api/v3/subtasks/{sid}/subtasks/create", headers=headers, json=body,
    )


# ---------------------------------------------------------------------------
# Optional on create — omit means unassigned
# ---------------------------------------------------------------------------

class TestOptionalOnCreate:
    def test_task_create_without_assignedTo_defaults_to_null(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        r = _make_task(client, admin_headers, a["id"])
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["assignedTo"] is None
        assert body["assignedToName"] is None

    def test_subtask_create_without_assignedTo_defaults_to_null(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(client, admin_headers, a["id"]).json()["data"]
        r = _make_subtask(client, admin_headers, t["id"])
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["assignedTo"] is None
        assert body["assignedToName"] is None

    def test_nested_create_without_assignedTo_defaults_to_null(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(client, admin_headers, a["id"]).json()["data"]
        s = _make_subtask(client, admin_headers, t["id"]).json()["data"]
        r = _make_nested(client, admin_headers, s["id"])
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["assignedTo"] is None
        assert body["assignedToName"] is None


# ---------------------------------------------------------------------------
# Round-trip when supplied — id stored, name resolved
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_task_assigned_round_trips(
        self, client, admin_headers, alice_user,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        r = _make_task(client, admin_headers, a["id"], assigned_to=alice_user.id)
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["assignedTo"] == alice_user.id
        assert body["assignedToName"] == "Alice Wonder"

    def test_subtask_assigned_round_trips(
        self, client, admin_headers, alice_user,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(client, admin_headers, a["id"]).json()["data"]
        r = _make_subtask(
            client, admin_headers, t["id"], assigned_to=alice_user.id,
        )
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["assignedTo"] == alice_user.id
        assert body["assignedToName"] == "Alice Wonder"

    def test_nested_assigned_round_trips(
        self, client, admin_headers, alice_user,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(client, admin_headers, a["id"]).json()["data"]
        s = _make_subtask(client, admin_headers, t["id"]).json()["data"]
        r = _make_nested(
            client, admin_headers, s["id"], assigned_to=alice_user.id,
        )
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["assignedTo"] == alice_user.id
        assert body["assignedToName"] == "Alice Wonder"


# ---------------------------------------------------------------------------
# Negative cases — invalid users rejected on create + on PATCH
# ---------------------------------------------------------------------------

class TestInvalidAssigneesRejected:
    def test_task_unknown_user_rejected_on_create(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        bogus = str(uuid4())
        r = _make_task(client, admin_headers, a["id"], assigned_to=bogus)
        assert r.status_code == 422
        assert "does not exist" in r.text.lower()

    def test_task_inactive_user_rejected_on_create(
        self, client, admin_headers, inactive_user,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        r = _make_task(client, admin_headers, a["id"], assigned_to=inactive_user.id)
        assert r.status_code == 422
        assert "not active" in r.text.lower()

    def test_task_deleted_user_rejected_on_create(
        self, client, admin_headers, deleted_user,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        r = _make_task(client, admin_headers, a["id"], assigned_to=deleted_user.id)
        assert r.status_code == 422
        assert "deleted" in r.text.lower()

    def test_subtask_unknown_user_rejected_on_create(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(client, admin_headers, a["id"]).json()["data"]
        r = _make_subtask(client, admin_headers, t["id"], assigned_to=str(uuid4()))
        assert r.status_code == 422

    def test_task_patch_unknown_user_rejected(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(client, admin_headers, a["id"]).json()["data"]
        r = client.patch(
            f"/api/v3/tasks/{t['id']}", headers=admin_headers,
            json={"assignedTo": str(uuid4())},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# PATCH semantics: change / unassign / no-change-on-omit
# ---------------------------------------------------------------------------

class TestPatchSemantics:
    def test_patch_changes_assignment(
        self, client, admin_headers, alice_user,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(client, admin_headers, a["id"]).json()["data"]
        # Initially unassigned.
        r = client.patch(
            f"/api/v3/tasks/{t['id']}", headers=admin_headers,
            json={"assignedTo": alice_user.id},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["assignedTo"] == alice_user.id
        assert r.json()["data"]["assignedToName"] == "Alice Wonder"

    def test_patch_null_unassigns(
        self, client, admin_headers, alice_user,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(
            client, admin_headers, a["id"], assigned_to=alice_user.id,
        ).json()["data"]
        assert t["assignedTo"] == alice_user.id
        r = client.patch(
            f"/api/v3/tasks/{t['id']}", headers=admin_headers,
            json={"assignedTo": None},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["assignedTo"] is None
        assert r.json()["data"]["assignedToName"] is None

    def test_patch_omit_leaves_assignment_unchanged(
        self, client, admin_headers, alice_user,
    ):
        """Omit ``assignedTo`` from the PATCH body — existing assignment
        must NOT be cleared (distinguishes omitted from explicit null)."""
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(
            client, admin_headers, a["id"], assigned_to=alice_user.id,
        ).json()["data"]
        # PATCH a different field, leaving assignedTo absent.
        r = client.patch(
            f"/api/v3/tasks/{t['id']}", headers=admin_headers,
            json={"description": "edited body — assignedTo omitted"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["assignedTo"] == alice_user.id
        assert r.json()["data"]["description"] == "edited body — assignedTo omitted"

    def test_subtask_patch_assigns_and_unassigns(
        self, client, admin_headers, alice_user,
    ):
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(client, admin_headers, a["id"]).json()["data"]
        s = _make_subtask(client, admin_headers, t["id"]).json()["data"]
        assigned = client.patch(
            f"/api/v3/subtasks/{s['id']}", headers=admin_headers,
            json={"assignedTo": alice_user.id},
        )
        assert assigned.status_code == 200
        assert assigned.json()["data"]["assignedTo"] == alice_user.id
        cleared = client.patch(
            f"/api/v3/subtasks/{s['id']}", headers=admin_headers,
            json={"assignedTo": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["data"]["assignedTo"] is None


# ---------------------------------------------------------------------------
# Independence — each level holds its own assignee, no cascade
# ---------------------------------------------------------------------------

class TestIndependence:
    def test_each_level_holds_its_own_assignee(
        self, client, admin_headers, alice_user,
    ):
        """Three different assignees down the chain to confirm there's no
        parent-child rule: T = admin, S = alice, nested = unassigned."""
        _pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(
            client, admin_headers, a["id"], assigned_to=_ADMIN_UUID,
        ).json()["data"]
        s = _make_subtask(
            client, admin_headers, t["id"], assigned_to=alice_user.id,
        ).json()["data"]
        n = _make_nested(client, admin_headers, s["id"]).json()["data"]
        assert t["assignedTo"] == _ADMIN_UUID
        assert s["assignedTo"] == alice_user.id
        assert n["assignedTo"] is None


# ---------------------------------------------------------------------------
# Tree response surfaces the field on T / S / nested but NOT M / A
# ---------------------------------------------------------------------------

class TestTreeSurfaces:
    def test_tree_emits_assignedTo_on_t_s_nested(
        self, client, admin_headers, alice_user,
    ):
        pid, _vid, _m, a = _setup_published_activity(client, admin_headers)
        t = _make_task(
            client, admin_headers, a["id"], assigned_to=_ADMIN_UUID,
        ).json()["data"]
        s = _make_subtask(
            client, admin_headers, t["id"], assigned_to=alice_user.id,
        ).json()["data"]
        _make_nested(client, admin_headers, s["id"])

        tree = client.get(
            f"/api/v3/projects/{pid}/tree", headers=admin_headers,
        ).json()["data"]
        m_node = tree["milestones"][0]
        a_node = m_node["activities"][0]
        t_node = a_node["tasks"][0]
        s_node = t_node["subtasks"][0]
        n_node = s_node["subtasks"][0]

        # T / S / nested-S DO carry the field.
        assert t_node["assignedTo"] == _ADMIN_UUID
        # admin user has no first/last name in the conftest fixture, so
        # the resolver falls back to the login.
        assert t_node["assignedToName"] == "admin"
        assert s_node["assignedTo"] == alice_user.id
        assert s_node["assignedToName"] == "Alice Wonder"
        assert n_node["assignedTo"] is None
        assert n_node["assignedToName"] is None

        # M / A intentionally do NOT carry the field.
        assert "assignedTo" not in m_node
        assert "assignedToName" not in m_node
        assert "assignedTo" not in a_node
        assert "assignedToName" not in a_node
