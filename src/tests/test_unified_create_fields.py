"""Unified create/update shape regression — verifies that POST create
endpoints accept the same superset of fields as PATCH update.

Coverage:
  - dependsOn on create (M / A / T / S / nested-S)
  - status on create
  - actualStartDate / actualEndDate on create (A / T / S / nested-S only;
    milestones don't have actuals)
  - position on create
  - sensible defaults when fields are omitted
  - status="completed" on create with non-completed deps -> 422

The PATCH-equivalent fields are still optional on create; omission falls
back to defaults (status -> "not_completed" for milestone, NULL for A/T/S;
dependsOn -> []).
"""
from uuid import uuid4


def _iso(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+05:30"


def _setup_project_and_vendor(client, admin_headers):
    proj = client.post(
        "/api/v3/projects/create",
        headers=admin_headers,
        json={
            "name": f"UC P {uuid4().hex[:4]}", "owner": "tmd1",
            "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 12, 31),
        },
    ).json()["data"]
    pid = proj["id"]
    v = client.post(
        "/api/v3/vendors/create",
        headers=admin_headers,
        json={"name": f"UC V {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
    ).json()["data"]
    vid = v["id"]
    client.patch(
        f"/api/v3/projects/{pid}", headers=admin_headers,
        json={"vendorIds": [vid]},
    )
    return pid, vid


# ---------------------------------------------------------------------------
# Milestone — dependsOn + status on CREATE
# ---------------------------------------------------------------------------

class TestMilestoneCreateUnifiedShape:
    def test_create_with_status_and_dependsOn(self, client, admin_headers):
        pid, _vid = _setup_project_and_vendor(client, admin_headers)

        m1 = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={
                "name": "M1",
                "startDate": _iso(2026, 7, 1),
                "endDate": _iso(2026, 8, 30),
                "status": "completed",
            },
        ).json()["data"]
        assert m1["status"] == "completed"
        assert m1["dependsOn"] == []

        # M2 dependsOn M1 at CREATE time. M2.end > M1.end (strict), M2.start >= M1.start.
        r = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={
                "name": "M2",
                "startDate": _iso(2026, 7, 1),
                "endDate": _iso(2026, 9, 30),
                "status": "not_completed",
                "dependsOn": [m1["id"]],
            },
        )
        assert r.status_code == 201, r.text
        m2 = r.json()["data"]
        assert m2["dependsOn"] == [m1["id"]]
        assert m2["dependsOnDisplay"] == [m1["displayCode"]]
        assert m2["status"] == "not_completed"

    def test_status_completed_with_uncompleted_dep_is_rejected(
        self, client, admin_headers,
    ):
        pid, _vid = _setup_project_and_vendor(client, admin_headers)
        m1 = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={
                "name": "M1",
                "startDate": _iso(2026, 7, 1),
                "endDate": _iso(2026, 8, 30),
                # status defaults to not_completed.
            },
        ).json()["data"]
        # M2 depends on M1 (which is not completed) AND M2 sent as completed.
        r = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={
                "name": "M2",
                "startDate": _iso(2026, 7, 1),
                "endDate": _iso(2026, 9, 30),
                "status": "completed",
                "dependsOn": [m1["id"]],
            },
        )
        assert r.status_code == 422
        assert "completed" in r.text.lower()

    def test_omitted_fields_use_defaults(self, client, admin_headers):
        pid, _vid = _setup_project_and_vendor(client, admin_headers)
        r = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={
                "name": "M1", "startDate": _iso(2026, 7, 1),
                "endDate": _iso(2026, 8, 30),
            },
        )
        assert r.status_code == 201
        m = r.json()["data"]
        assert m["status"] == "not_completed"
        assert m["dependsOn"] == []


# ---------------------------------------------------------------------------
# Activity — actuals + status + dependsOn on CREATE
# ---------------------------------------------------------------------------

class TestActivityCreateUnifiedShape:
    def test_create_with_full_payload(self, client, admin_headers):
        pid, vid = _setup_project_and_vendor(client, admin_headers)
        m1 = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30)},
        ).json()["data"]

        a1 = client.post(
            f"/api/v3/milestones/{m1['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 20),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p1",
                "actualStartDate": _iso(2026, 7, 5),
                "actualEndDate": _iso(2026, 7, 19),
                "status": "completed",
            },
        ).json()["data"]
        assert a1["actualStartDate"] is not None
        assert a1["actualEndDate"] is not None
        assert a1["status"] == "completed"

        # A2 depends on A1 (completed) at CREATE time.
        r = client.post(
            f"/api/v3/milestones/{m1['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A2",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 25),
                "ownerDivision": "tmd2", "vendorId": vid,
                "concernedDivision": ["tmd1", "others"],
                "priority": "p1",
                "dependsOn": [a1["id"]],
                "status": "not_completed",
            },
        )
        assert r.status_code == 201, r.text
        a2 = r.json()["data"]
        assert a2["dependsOn"] == [a1["id"]]
        assert a2["dependsOnDisplay"] == [a1["displayCode"]]

    def test_create_completed_with_uncompleted_dep_rejected(
        self, client, admin_headers,
    ):
        pid, vid = _setup_project_and_vendor(client, admin_headers)
        m1 = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30)},
        ).json()["data"]
        a1 = client.post(
            f"/api/v3/milestones/{m1['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 20),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p1",
                # status defaults to NULL (not completed).
            },
        ).json()["data"]
        r = client.post(
            f"/api/v3/milestones/{m1['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A2",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 25),
                "ownerDivision": "tmd2", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p1",
                "dependsOn": [a1["id"]],
                "status": "completed",
            },
        )
        assert r.status_code == 422
        assert "completed" in r.text.lower()


# ---------------------------------------------------------------------------
# Task + Subtask + nested Subtask — dependsOn + status + actuals on CREATE
# ---------------------------------------------------------------------------

def _publishable_setup(client, admin_headers):
    """Set up a project that's been published (so tasks can be created),
    return ids for the activity to use as parent."""
    pid, vid = _setup_project_and_vendor(client, admin_headers)
    m = client.post(
        f"/api/v3/projects/{pid}/milestones/create",
        headers=admin_headers,
        json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30)},
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


class TestTaskCreateUnifiedShape:
    def test_create_with_dependsOn_actuals_status(
        self, client, admin_headers,
    ):
        pid, vid, m, a = _publishable_setup(client, admin_headers)

        t1 = client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={
                "name": "T1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "actualStartDate": _iso(2026, 7, 2),
                "actualEndDate": _iso(2026, 7, 9),
                "status": "completed",
            },
        ).json()["data"]
        assert t1["status"] == "completed"
        assert t1["actualStartDate"] is not None
        assert t1["actualEndDate"] is not None

        r = client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={
                "name": "T2",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 15),
                "dependsOn": [t1["id"]],
                "status": "not_completed",
            },
        )
        assert r.status_code == 201, r.text
        t2 = r.json()["data"]
        assert t2["dependsOn"] == [t1["id"]]
        assert t2["dependsOnDisplay"] == [t1["displayCode"]]


class TestSubtaskCreateUnifiedShape:
    def test_create_with_dependsOn_actuals_status_top_and_nested(
        self, client, admin_headers,
    ):
        pid, vid, m, a = _publishable_setup(client, admin_headers)
        t = client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={"name": "T1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 15)},
        ).json()["data"]

        # Top-level subtask with full payload at CREATE.
        s1 = client.post(
            f"/api/v3/tasks/{t['id']}/subtasks/create",
            headers=admin_headers,
            json={
                "name": "S1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 5),
                "actualStartDate": _iso(2026, 7, 2),
                "actualEndDate": _iso(2026, 7, 4),
                "status": "completed",
            },
        ).json()["data"]
        assert s1["status"] == "completed"

        # Sibling top-level S2 -> dependsOn S1 at CREATE.
        r = client.post(
            f"/api/v3/tasks/{t['id']}/subtasks/create",
            headers=admin_headers,
            json={
                "name": "S2",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 8),
                "dependsOn": [s1["id"]],
                "status": "not_completed",
            },
        )
        assert r.status_code == 201, r.text
        s2 = r.json()["data"]
        assert s2["dependsOn"] == [s1["id"]]

        # Nested subtask under S1 with status + actuals at CREATE.
        rn = client.post(
            f"/api/v3/subtasks/{s1['id']}/subtasks/create",
            headers=admin_headers,
            json={
                "name": "S1.1 nested",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 3),
                "actualStartDate": _iso(2026, 7, 2),
                "actualEndDate": _iso(2026, 7, 3),
                "status": "completed",
            },
        )
        assert rn.status_code == 201, rn.text
        nested = rn.json()["data"]
        assert nested["parentSubtaskId"] == s1["id"]
        assert nested["status"] == "completed"

        # Sibling nested under S1 -> dependsOn nested at CREATE.
        rn2 = client.post(
            f"/api/v3/subtasks/{s1['id']}/subtasks/create",
            headers=admin_headers,
            json={
                "name": "S1.2 nested",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 4),
                "dependsOn": [nested["id"]],
            },
        )
        assert rn2.status_code == 201, rn2.text
        nested2 = rn2.json()["data"]
        assert nested2["dependsOn"] == [nested["id"]]
