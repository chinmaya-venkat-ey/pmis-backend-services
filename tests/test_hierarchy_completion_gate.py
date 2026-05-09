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
  - Reverse direction: top-down strict — a child cannot be reverted
    while its parent is still ``completed``. Milestone has no parent
    and is therefore unguarded on revert.

Pairs with the existing milestone gate (commit 6c1ff47) — together
the four levels form the complete completion hierarchy.
"""
from uuid import uuid4


def _iso(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+05:30"


def _setup(client, admin_headers):
    """Project + vendor (no milestone/activity yet). Returns (pid, vid)."""
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
    return pid, vid


def _setup_and_publish(client, admin_headers):
    """Project + vendor + milestone + activity, then publish so we can
    create tasks/subtasks under it. Returns ids."""
    pid, vid = _setup(client, admin_headers)
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
    def test_revert_allowed_when_children_already_not_completed(
        self, client, admin_headers,
    ):
        """Reverting is allowed when no child is still ``completed``.
        Empty-children case: a milestone with no activities can be
        flipped to completed and reverted freely."""
        pid, vid, _m, _a = _setup_and_publish(client, admin_headers)
        m2 = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M2 empty", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30), "priority": "p1"},
        ).json()["data"]
        # Empty milestone: forward + reverse both no-op.
        c = client.patch(
            f"/api/v3/milestones/{m2['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        assert c.status_code == 200, c.text
        r = client.patch(
            f"/api/v3/milestones/{m2['id']}", headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 200, r.text


class TestRevertBlockedWhenParentStillCompleted:
    """Tester-feedback fix: top-down uncomplete model.

    A node can only be reverted to ``not_completed`` once its parent
    is also ``not_completed``. This prevents the "parent=completed but
    child=not_completed" inconsistency the tester reproduced — which
    was reachable previously by reverting a leaf task or leaf subtask
    while ancestors were still ``completed``.

    Milestone reverts are not gated here because a milestone has no
    completion-relevant parent (the project lifecycle status is
    separate). See ``TestMilestoneRevertAlwaysAllowed`` below for that.
    """

    def test_subtask_revert_blocked_when_parent_subtask_still_completed(
        self, client, admin_headers,
    ):
        """Nested subtask can't be reverted while its parent subtask
        is still completed."""
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
            json={"name": "S1.1 nested", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 5), "priority": "p1"},
        ).json()["data"]
        # Bottom-up complete (forward gate setup).
        for url in (
            f"/api/v3/subtasks/{nested['id']}",
            f"/api/v3/subtasks/{s['id']}",
            f"/api/v3/tasks/{t['id']}",
        ):
            client.patch(url, headers=admin_headers, json={"status": "completed"})
        # Try to revert nested S → blocked (parent S1 still completed).
        r = client.patch(
            f"/api/v3/subtasks/{nested['id']}", headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 422, r.text
        assert "S1" in r.text
        assert "parent" in r.text.lower()

    def test_subtask_revert_blocked_when_parent_task_still_completed(
        self, client, admin_headers,
    ):
        """Top-level subtask can't be reverted while its parent task
        is still completed."""
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
        # Bottom-up complete.
        client.patch(
            f"/api/v3/subtasks/{s['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        client.patch(
            f"/api/v3/tasks/{t['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        # Try to revert S → blocked (parent T1 still completed).
        r = client.patch(
            f"/api/v3/subtasks/{s['id']}", headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 422, r.text
        assert "T1" in r.text
        assert "parent" in r.text.lower()

    def test_task_revert_blocked_when_parent_activity_still_completed(
        self, client, admin_headers,
    ):
        """LEAF task case — was reachable under the old model: revert
        of a leaf task with no subtasks let the user produce the
        documented inconsistent state. The new gate blocks it."""
        pid, vid, m, a = _setup_and_publish(client, admin_headers)
        t = client.post(
            f"/api/v3/activities/{a['id']}/tasks/create",
            headers=admin_headers,
            json={
                "name": "T-leaf",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 15),
                "priority": "p1", "status": "completed",
            },
        ).json()["data"]
        client.patch(
            f"/api/v3/activities/{a['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        # Revert leaf task → blocked (parent activity A1 still completed).
        r = client.patch(
            f"/api/v3/tasks/{t['id']}", headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 422, r.text
        assert "A1" in r.text
        assert "parent" in r.text.lower()

    def test_activity_revert_blocked_when_parent_milestone_still_completed(
        self, client, admin_headers,
    ):
        pid, vid = _setup(client, admin_headers)
        m = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30), "priority": "p1"},
        ).json()["data"]
        a = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A-done",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p1",
                "status": "completed",
            },
        ).json()["data"]
        client.patch(
            f"/api/v3/milestones/{m['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        # Revert activity → blocked (parent milestone M1 still completed).
        r = client.patch(
            f"/api/v3/activities/{a['id']}", headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 422, r.text
        assert "M1" in r.text
        assert "parent" in r.text.lower()


class TestMilestoneRevertAlwaysAllowed:
    """Milestone has no completion-relevant parent (project lifecycle
    status is unrelated), so reverting a milestone is always permitted
    even when child activities are still ``completed``.

    Behavior change vs. the previous model — the user explicitly chose
    this so the top-down uncomplete sequence has a starting point at
    the top of the tree.
    """

    def test_milestone_revert_succeeds_with_completed_children(
        self, client, admin_headers,
    ):
        pid, vid = _setup(client, admin_headers)
        m = client.post(
            f"/api/v3/projects/{pid}/milestones/create",
            headers=admin_headers,
            json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30), "priority": "p1"},
        ).json()["data"]
        client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A-done",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p1",
                "status": "completed",
            },
        )
        client.patch(
            f"/api/v3/milestones/{m['id']}", headers=admin_headers,
            json={"status": "completed"},
        )
        r = client.patch(
            f"/api/v3/milestones/{m['id']}", headers=admin_headers,
            json={"status": "not_completed"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "not_completed"


class TestTopDownUncomplete:
    """Once everything is completed, the only legal revert order is
    top-down (parent first). Mirror of the previous BottomUpUncomplete
    test — assertions inverted to match the new model."""

    def test_full_uncomplete_cascade_top_down(
        self, client, admin_headers,
    ):
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
        # Bottom-up complete (forward gate setup).
        for url in (
            f"/api/v3/subtasks/{nested['id']}",
            f"/api/v3/subtasks/{s['id']}",
            f"/api/v3/tasks/{t['id']}",
            f"/api/v3/activities/{a['id']}",
            f"/api/v3/milestones/{m['id']}",
        ):
            r = client.patch(url, headers=admin_headers, json={"status": "completed"})
            assert r.status_code == 200, f"complete {url}: {r.text}"

        # Bottom-up uncomplete attempts must all fail under the new
        # top-down model — even the leaf is blocked while its parent
        # is still completed.
        for url in (
            f"/api/v3/subtasks/{nested['id']}",
            f"/api/v3/subtasks/{s['id']}",
            f"/api/v3/tasks/{t['id']}",
            f"/api/v3/activities/{a['id']}",
        ):
            r = client.patch(url, headers=admin_headers, json={"status": "not_completed"})
            assert r.status_code == 422, f"bottom-up revert at {url} should fail: {r.text}"

        # Top-down uncomplete cascade — each must succeed once its
        # parent is already not_completed.
        for url in (
            f"/api/v3/milestones/{m['id']}",
            f"/api/v3/activities/{a['id']}",
            f"/api/v3/tasks/{t['id']}",
            f"/api/v3/subtasks/{s['id']}",
            f"/api/v3/subtasks/{nested['id']}",
        ):
            r = client.patch(url, headers=admin_headers, json={"status": "not_completed"})
            assert r.status_code == 200, f"top-down revert at {url} should succeed: {r.text}"
            assert r.json()["data"]["status"] == "not_completed"
