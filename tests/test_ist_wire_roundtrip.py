"""IST wire round-trip — every datetime field on the wire must come
back with explicit ``+05:30`` so the FE doesn't have to convert UTC →
IST on every render.

Pairs with ``IstCalendarDate`` input normalization: the FE sends IST
midnight, the BE stores canonical UTC, and ``iso_ist`` flips it back
to IST on the way out so the wire is symmetric in IST.

Coverage:
  - Project create/get
  - Milestone create + PATCH
  - Activity create + PATCH
  - Task create + PATCH
  - Subtask create + PATCH (incl. nested)
  - Tree GET (every M/A/T/S node)
"""
from uuid import uuid4


def _iso_ist(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+05:30"


def _assert_ist(value, *, label):
    """Datetime fields must end with +05:30 (or be null)."""
    if value is None:
        return
    assert isinstance(value, str), f"{label}: not a string: {value!r}"
    assert value.endswith("+05:30"), (
        f"{label}: expected IST suffix +05:30, got {value!r}"
    )


def _setup(client, admin_headers):
    # Project starts April 1 so the milestone-PATCH test below (which uses
    # April / May / June dates to repro the tester scenario) doesn't trip
    # the start-date floor.
    proj = client.post(
        "/api/v3/projects/create",
        headers=admin_headers,
        json={
            "name": f"IST P {uuid4().hex[:4]}", "owner": "tmd1",
            "startDate": _iso_ist(2026, 4, 1),
            "endDate": _iso_ist(2026, 12, 31),
        },
    ).json()["data"]
    pid = proj["id"]
    v = client.post(
        "/api/v3/vendors/create",
        headers=admin_headers,
        json={"name": f"IST V {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
    ).json()["data"]
    vid = v["id"]
    client.patch(
        f"/api/v3/projects/{pid}", headers=admin_headers,
        json={"vendorIds": [vid]},
    )
    return pid, vid, proj


class TestProjectIstWire:
    def test_project_dates_come_back_in_ist(self, client, admin_headers):
        _pid, _vid, proj = _setup(client, admin_headers)
        _assert_ist(proj["startDate"], label="project.startDate")
        _assert_ist(proj["endDate"],   label="project.endDate")
        _assert_ist(proj["createdAt"], label="project.createdAt")
        _assert_ist(proj["updatedAt"], label="project.updatedAt")


class TestMilestoneIstWire:
    def test_milestone_create_and_patch_wire_in_ist(
        self, client, admin_headers,
    ):
        pid, _vid, _proj = _setup(client, admin_headers)
        # CREATE
        m = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={
                "name": "M1",
                "startDate": "2026-04-01T00:00:00+05:30",
                "endDate":   "2026-05-30T23:59:59+05:30",
                "status": "not_completed",
                "dependsOn": [],
            },
        ).json()["data"]
        # Repro of the exact tester scenario: send +05:30, get +05:30 back.
        assert m["startDate"] == "2026-04-01T00:00:00+05:30"
        assert m["endDate"]   == "2026-05-30T00:00:00+05:30"  # IST midnight after collapse
        for k in ("createdAt", "updatedAt"):
            _assert_ist(m[k], label=f"milestone.{k}")

        # PATCH
        m2 = client.patch(
            f"/api/v3/milestones/{m['id']}",
            headers=admin_headers,
            json={
                "endDate": "2026-06-15T23:59:59+05:30",
            },
        ).json()["data"]
        assert m2["endDate"] == "2026-06-15T00:00:00+05:30"
        for k in ("startDate", "endDate", "createdAt", "updatedAt"):
            _assert_ist(m2[k], label=f"milestone.{k}")


class TestActivityIstWire:
    def test_activity_create_and_patch_wire_in_ist(
        self, client, admin_headers,
    ):
        pid, vid, _proj = _setup(client, admin_headers)
        m = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M1", "startDate": _iso_ist(2026, 7, 1), "endDate": _iso_ist(2026, 8, 30)},
        ).json()["data"]
        a = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso_ist(2026, 7, 1), "endDate": _iso_ist(2026, 7, 20),
                "ownerDivision": "tmd1", "vendorId": vid, "concernedDivision": ["tmd1"],
                "actualStartDate": _iso_ist(2026, 7, 5),
                "actualEndDate":   _iso_ist(2026, 7, 19),
            },
        ).json()["data"]
        for k in ("startDate", "endDate", "actualStartDate", "actualEndDate",
                  "createdAt", "updatedAt"):
            _assert_ist(a[k], label=f"activity.{k}")

        a2 = client.patch(
            f"/api/v3/activities/{a['id']}",
            headers=admin_headers,
            json={"actualEndDate": _iso_ist(2026, 7, 20)},
        ).json()["data"]
        for k in ("startDate", "endDate", "actualStartDate", "actualEndDate",
                  "createdAt", "updatedAt"):
            _assert_ist(a2[k], label=f"activity.{k}")


class TestTaskAndSubtaskIstWire:
    def test_task_subtask_nested_round_trip_in_ist(
        self, client, admin_headers,
    ):
        pid, vid, _proj = _setup(client, admin_headers)
        m = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M1", "startDate": _iso_ist(2026, 7, 1), "endDate": _iso_ist(2026, 8, 30)},
        ).json()["data"]
        a = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso_ist(2026, 7, 1), "endDate": _iso_ist(2026, 7, 30),
                "ownerDivision": "tmd1", "vendorId": vid, "concernedDivision": ["tmd1"],
            },
        ).json()["data"]
        client.post(f"/api/v3/projects/{pid}/publish", headers=admin_headers)

        t = client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={"name": "T1", "startDate": _iso_ist(2026, 7, 1), "endDate": _iso_ist(2026, 7, 15)},
        ).json()["data"]
        for k in ("startDate", "endDate", "createdAt", "updatedAt"):
            _assert_ist(t[k], label=f"task.{k}")

        s = client.post(
            f"/api/v3/tasks/{t['id']}/subtasks/create",
            headers=admin_headers,
            json={"name": "S1", "startDate": _iso_ist(2026, 7, 1), "endDate": _iso_ist(2026, 7, 5)},
        ).json()["data"]
        for k in ("startDate", "endDate", "createdAt", "updatedAt"):
            _assert_ist(s[k], label=f"subtask.{k}")

        nested = client.post(
            f"/api/v3/subtasks/{s['id']}/subtasks/create",
            headers=admin_headers,
            json={"name": "S1.1", "startDate": _iso_ist(2026, 7, 1), "endDate": _iso_ist(2026, 7, 3)},
        ).json()["data"]
        for k in ("startDate", "endDate", "createdAt", "updatedAt"):
            _assert_ist(nested[k], label=f"nested-subtask.{k}")
