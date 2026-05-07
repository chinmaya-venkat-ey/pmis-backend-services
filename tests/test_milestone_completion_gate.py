"""Milestone completion gate — children-completed rule.

Tester ask: a milestone may only flip to ``status="completed"`` once
every child activity under it is also ``completed``. Mirrors the
existing dep-target gate in scope (status="completed" only) but
checks the parent-child rollup instead of cross-edges.

Soft-deleted activities are out of scope for the rollup. Reverting a
milestone back to ``not_completed`` is always allowed regardless of
child state — only the forward transition is gated.
"""
from uuid import uuid4


def _iso(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+05:30"


def _setup(client, admin_headers):
    proj = client.post(
        "/api/v3/projects/create",
        headers=admin_headers,
        json={
            "name": f"GP {uuid4().hex[:4]}", "owner": "tmd1",
            "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 12, 31),
        },
    ).json()["data"]
    pid = proj["id"]
    v = client.post(
        "/api/v3/vendors/create",
        headers=admin_headers,
        json={"name": f"GP V {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
    ).json()["data"]
    vid = v["id"]
    client.patch(
        f"/api/v3/projects/{pid}", headers=admin_headers,
        json={"vendorIds": [vid]},
    )
    return pid, vid


class TestMilestoneChildrenGate:
    def test_complete_blocked_when_any_activity_not_completed(
        self, client, admin_headers,
    ):
        pid, vid = _setup(client, admin_headers)
        m = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30)},
        ).json()["data"]
        # Two child activities — one completed, one not.
        a1 = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "ownerDivision": "tmd1", "vendorId": vid, "concernedDivision": ["tmd1"],
                "priority": "p1",
                "status": "completed",
            },
        ).json()["data"]
        a2 = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A2 still-running",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 20),
                "ownerDivision": "tmd1", "vendorId": vid, "concernedDivision": ["tmd1"],
                "priority": "p1",
                # status defaults to NULL — definitely not completed.
            },
        ).json()["data"]
        assert a1["status"] == "completed"
        assert a2["status"] is None

        # Try to flip milestone to completed — must fail with 422 + names.
        r = client.patch(
            f"/api/v3/milestones/{m['id']}",
            headers=admin_headers,
            json={"status": "completed"},
        )
        assert r.status_code == 422, r.text
        body = r.json()
        # Error message should reference the offending child name.
        assert "A2 still-running" in r.text
        # And the helpful "child activit..." phrase from the gate.
        assert "child activit" in r.text.lower()

    def test_complete_allowed_when_all_activities_completed(
        self, client, admin_headers,
    ):
        pid, vid = _setup(client, admin_headers)
        m = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30)},
        ).json()["data"]
        for name, end in (("A1", 10), ("A2", 12)):
            client.post(
                f"/api/v3/milestones/{m['id']}/activities/create",
                headers=admin_headers,
                json={
                    "name": name,
                    "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, end),
                    "ownerDivision": "tmd1", "vendorId": vid, "concernedDivision": ["tmd1"],
                    "priority": "p1",
                    "status": "completed",
                },
            )

        r = client.patch(
            f"/api/v3/milestones/{m['id']}",
            headers=admin_headers,
            json={"status": "completed"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "completed"

    def test_complete_allowed_when_no_activities_yet(
        self, client, admin_headers,
    ):
        """Empty milestone: no children to gate on. Allowed."""
        pid, _vid = _setup(client, admin_headers)
        m = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30)},
        ).json()["data"]
        r = client.patch(
            f"/api/v3/milestones/{m['id']}",
            headers=admin_headers,
            json={"status": "completed"},
        )
        assert r.status_code == 200, r.text

    def test_revert_to_not_completed_always_allowed(
        self, client, admin_headers,
    ):
        """The gate only fires on the forward transition to 'completed'.
        Moving back is unrestricted — child state is irrelevant."""
        pid, vid = _setup(client, admin_headers)
        m = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={
                "name": "M1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30),
                "status": "completed",  # empty children -> allowed
            },
        ).json()["data"]
        # Add an in-progress activity post-completion.
        client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1 retro",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 20),
                "ownerDivision": "tmd1", "vendorId": vid, "concernedDivision": ["tmd1"],
                "priority": "p1",
            },
        )
        # Now revert milestone to not_completed — must succeed even though
        # the child activity isn't completed.
        r = client.patch(
            f"/api/v3/milestones/{m['id']}",
            headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "not_completed"
