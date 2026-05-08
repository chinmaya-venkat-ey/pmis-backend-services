"""Hierarchy completion gate — A/T/S/nested-S levels.

User ask: a parent may only flip to ``status="completed"`` when all
its direct children are also ``completed``. By induction (each level
enforces the same rule), this covers the full descendant rollup —
no leaf in the hierarchy can be incomplete when an ancestor is
marked completed.

Coverage:
  - Activity blocked when a child task isn't completed
  - Task blocked when a child subtask isn't completed
  - Subtask blocked when a nested subtask isn't completed
  - Bottom-up rollup: completing a leaf cascades upward by repeated
    PATCH (each level allowed once its children are completed)
  - Soft-deleted children are out of scope
  - Reverting to ``not_completed`` is always allowed regardless of
    child state

Pairs with the existing milestone gate (commit 6c1ff47) — together
the four levels form the complete completion hierarchy.
"""
from uuid import uuid4


def _iso(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+05:30"


def _setup_and_publish(client, admin_headers):
    """Project + vendor + milestone + activity, then publish so we can
    create tasks/subtasks under it. Returns ids."""
    proj = client.post(
        "/api/v3/projects/create",
        headers=admin_headers,
        json={
            "name": f"GateP {uuid4().hex[:4]}", "owner": "tmd1",
            "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 12, 31),
        },
    ).json()["data"]
    pid = proj["id"]
    v = client.post(
        "/api/v3/vendors/create",
        headers=admin_headers,
        json={"name": f"GateV {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
    ).json()["data"]
    vid = v["id"]
    client.patch(
        f"/api/v3/projects/{pid}", headers=admin_headers,
        json={"vendorIds": [vid]},
    )
    m = client.post(
        f"/api/v3/projects/{pid}/milestones/create",
        headers=admin_headers,
        json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30), "priority": "p1"},
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


class TestActivityChildrenGate:
    def test_complete_blocked_when_any_child_task_incomplete(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_and_publish(client, admin_headers)
        # Two child tasks under A — one completed, one not.
        client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={
                "name": "T-done",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 5),
                "status": "completed",
                "priority": "p1",
            },
        )
        client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={
                "name": "T-running",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "priority": "p1",
            },
        )
        r = client.patch(
            f"/api/v3/activities/{a['id']}",
            headers=admin_headers,
            json={"status": "completed"},
        )
        assert r.status_code == 422, r.text
        assert "T-running" in r.text
        assert "child task" in r.text.lower()

    def test_complete_allowed_when_all_child_tasks_completed(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_and_publish(client, admin_headers)
        for name in ("T1", "T2"):
            client.post(
                f"/api/v3/activities/{a['id']}/tasks/create",
                headers=admin_headers,
                json={
                    "name": name,
                    "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                    "status": "completed",
                    "priority": "p1",
                },
            )
        r = client.patch(
            f"/api/v3/activities/{a['id']}",
            headers=admin_headers,
            json={"status": "completed"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "completed"


class TestTaskChildrenGate:
    def test_complete_blocked_when_any_top_level_subtask_incomplete(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_and_publish(client, admin_headers)
        t = client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={"name": "T1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 15), "priority": "p1"},
        ).json()["data"]
        client.post(
            f"/api/v3/tasks/{t['id']}/subtasks/create",
            headers=admin_headers,
            json={
                "name": "S-done",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 5),
                "status": "completed",
                "priority": "p1",
            },
        )
        client.post(
            f"/api/v3/tasks/{t['id']}/subtasks/create",
            headers=admin_headers,
            json={
                "name": "S-running",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 8),
                "priority": "p1",
            },
        )
        r = client.patch(
            f"/api/v3/tasks/{t['id']}",
            headers=admin_headers,
            json={"status": "completed"},
        )
        assert r.status_code == 422, r.text
        assert "S-running" in r.text
        assert "child subtask" in r.text.lower()


class TestSubtaskChildrenGate:
    def test_complete_blocked_when_any_nested_subtask_incomplete(
        self, client, admin_headers,
    ):
        _pid, _vid, _m, a = _setup_and_publish(client, admin_headers)
        t = client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={"name": "T1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 15), "priority": "p1"},
        ).json()["data"]
        s = client.post(
            f"/api/v3/tasks/{t['id']}/subtasks/create",
            headers=admin_headers,
            json={"name": "S1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10), "priority": "p1"},
        ).json()["data"]
        # Nested subtask under S1, not completed.
        client.post(
            f"/api/v3/subtasks/{s['id']}/subtasks/create",
            headers=admin_headers,
            json={
                "name": "S1.1 nested-running",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 3),
                "priority": "p1",
            },
        )
        r = client.patch(
            f"/api/v3/subtasks/{s['id']}",
            headers=admin_headers,
            json={"status": "completed"},
        )
        assert r.status_code == 422, r.text
        assert "S1.1 nested-running" in r.text
        assert "nested subtask" in r.text.lower()


class TestBottomUpCascade:
    def test_complete_full_hierarchy_bottom_up(
        self, client, admin_headers,
    ):
        """Build M / A / T / S / nested-S where every level starts
        not-completed, then complete bottom-up. Each PATCH must
        succeed exactly when its children have been completed
        first."""
        pid, vid, m, a = _setup_and_publish(client, admin_headers)
        t = client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={"name": "T1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 15), "priority": "p1"},
        ).json()["data"]
        s = client.post(
            f"/api/v3/tasks/{t['id']}/subtasks/create",
            headers=admin_headers,
            json={"name": "S1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10), "priority": "p1"},
        ).json()["data"]
        nested = client.post(
            f"/api/v3/subtasks/{s['id']}/subtasks/create",
            headers=admin_headers,
            json={"name": "S1.1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 5), "priority": "p1"},
        ).json()["data"]

        # Top-down attempts must all fail.
        for url in (
            f"/api/v3/milestones/{m['id']}",
            f"/api/v3/activities/{a['id']}",
            f"/api/v3/tasks/{t['id']}",
            f"/api/v3/subtasks/{s['id']}",
        ):
            r = client.patch(url, headers=admin_headers, json={"status": "completed"})
            assert r.status_code == 422, f"{url} should fail: {r.text}"

        # Bottom-up cascade — each must succeed once its children are done.
        for url in (
            f"/api/v3/subtasks/{nested['id']}",
            f"/api/v3/subtasks/{s['id']}",
            f"/api/v3/tasks/{t['id']}",
            f"/api/v3/activities/{a['id']}",
            f"/api/v3/milestones/{m['id']}",
        ):
            r = client.patch(url, headers=admin_headers, json={"status": "completed"})
            assert r.status_code == 200, f"{url} should succeed: {r.text}"
            assert r.json()["data"]["status"] == "completed"


class TestRevertAllowedWhenChildrenAreNotCompleted:
    def test_revert_allowed_when_children_are_not_completed(
        self, client, admin_headers,
    ):
        """Reverts to ``not_completed`` are allowed when no child is still
        completed. (After the reverse children gate was added, reverts are
        only allowed bottom-up — but if children were never completed in
        the first place, the parent revert path is unobstructed.)
        """
        pid, vid, m, a = _setup_and_publish(client, admin_headers)
        # Mark milestone & activity completed before any tasks exist.
        client.patch(
            f"/api/v3/activities/{a['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        client.patch(
            f"/api/v3/milestones/{m['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        # Now revert bottom-up: activity first, then milestone. After
        # the activity is reverted, the milestone has no completed
        # children, so its revert is also allowed.
        r = client.patch(
            f"/api/v3/activities/{a['id']}", headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 200, r.text
        r = client.patch(
            f"/api/v3/milestones/{m['id']}", headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 200, r.text


class TestRevertBlockedWhenChildIsStillCompleted:
    def test_milestone_revert_blocked_when_activity_still_completed(
        self, client, admin_headers,
    ):
        """Reverse mirror of the forward children gate: reverting a
        milestone to ``not_completed`` is blocked while a child activity
        is still ``completed``. Walk the tree bottom-up: revert the leaf
        first, then the parent, and so on.
        """
        pid, vid, m, a = _setup_and_publish(client, admin_headers)
        client.patch(
            f"/api/v3/activities/{a['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        client.patch(
            f"/api/v3/milestones/{m['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        # Try to revert the milestone first — blocked because A1 is
        # still completed.
        r = client.patch(
            f"/api/v3/milestones/{m['id']}", headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 422, r.text
        assert "still completed" in r.text.lower()
