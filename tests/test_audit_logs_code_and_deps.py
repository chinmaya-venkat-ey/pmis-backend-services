"""Doc 54 — audit-logs row carries code + dependsOnDisplay
+ dependsOnDisplayBefore (mirror of monolith 2feefec).

Each row returned by ``GET /api/v3/projects/{uuid}/audit-logs`` now
carries:

  - ``code`` — for project.* actions, the project's projectCode; for
    M/A/T/S actions, the entity's current displayCode (M1 / A1.2 /
    T1.2.3 / S1.2.3.4). Null when the entity has been hard-deleted.
  - ``dependsOnDisplay`` — resolved labels from the audit-snapshot's
    ``after.depends_on``. Populated on ``*.create`` + ``*.dep_change``;
    null otherwise.
  - ``dependsOnDisplayBefore`` — resolved labels from the audit
    snapshot's ``before.depends_on``. Populated only on
    ``*.dep_change``; null otherwise.

The raw ``before`` / ``after`` JSON is preserved byte-for-byte; the
three new keys are additive.
"""
from uuid import uuid4

import pytest

from app.infrastructure.db.models.project_audit_log import ProjectAuditLogModel


def _iso(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+05:30"


@pytest.fixture
def project_via_api(client, admin_headers):
    """Create a project through the real POST so it generates a
    project.create audit row through the normal record_audit path."""
    r = client.post(
        "/api/v3/projects/create",
        headers=admin_headers,
        json={
            "name": f"Audit P {uuid4().hex[:4]}",
            "owner": "tmd1",
            "startDate": _iso(2026, 7, 1),
            "endDate": _iso(2026, 12, 31),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


class TestProjectLevelRow:
    def test_project_create_row_has_projectcode_as_code(
        self, client, admin_headers, project_via_api,
    ):
        r = client.get(
            f"/api/v3/projects/{project_via_api['id']}/audit-logs",
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        rows = r.json()["data"]["_embedded"]["elements"]
        assert rows, "expected at least one project.create row"
        create_row = next(
            x for x in rows if x["action"].startswith("project.")
        )
        assert create_row["code"] == project_via_api["projectCode"]
        assert create_row["dependsOnDisplay"] is None
        assert create_row["dependsOnDisplayBefore"] is None


class TestMilestoneRows:
    def test_milestone_create_carries_M1_displaycode(
        self, client, admin_headers, project_via_api,
    ):
        m = client.post(
            f"/api/v3/projects/{project_via_api['id']}/milestones/create",
            headers=admin_headers,
            json={
                "name": "First M",
                "startDate": _iso(2026, 7, 1),
                "endDate": _iso(2026, 8, 30),
                "priority": "p1",
            },
        )
        assert m.status_code == 201, m.text

        r = client.get(
            f"/api/v3/projects/{project_via_api['id']}/audit-logs",
            headers=admin_headers,
        )
        rows = r.json()["data"]["_embedded"]["elements"]
        ms_row = next(x for x in rows if x["action"] == "milestone.create")
        # Single milestone in the project — its displayCode is M1.
        assert ms_row["code"] == "M1"
        assert ms_row["dependsOnDisplay"] == []

    def test_milestone_dep_change_resolves_to_label_list(
        self, client, admin_headers, project_via_api, db_session,
    ):
        # Two milestones, then a dep_change on the second pointing at
        # the first. M1 is the target → dependsOnDisplay should be ["M1"]
        # on the M2's most-recent audit row (dep_change).
        m1 = client.post(
            f"/api/v3/projects/{project_via_api['id']}/milestones/create",
            headers=admin_headers,
            json={
                "name": "Earlier",
                "startDate": _iso(2026, 7, 1),
                "endDate": _iso(2026, 7, 15),
                "priority": "p1",
            },
        ).json()["data"]
        m2 = client.post(
            f"/api/v3/projects/{project_via_api['id']}/milestones/create",
            headers=admin_headers,
            json={
                "name": "Later",
                "startDate": _iso(2026, 7, 20),
                "endDate": _iso(2026, 8, 30),
                "priority": "p1",
            },
        ).json()["data"]
        # Add M2 dependsOn M1.
        r = client.patch(
            f"/api/v3/milestones/{m2['id']}",
            headers=admin_headers,
            json={"dependsOn": [m1["id"]]},
        )
        assert r.status_code == 200, r.text

        r = client.get(
            f"/api/v3/projects/{project_via_api['id']}/audit-logs",
            headers=admin_headers,
        )
        rows = r.json()["data"]["_embedded"]["elements"]
        # Find the dep_change row for the second milestone.
        dep_rows = [
            x for x in rows
            if x["action"] == "milestone.dep_change"
            and x["code"] == "M2"
        ]
        assert dep_rows, "expected milestone.dep_change row for M2"
        assert dep_rows[0]["dependsOnDisplay"] == ["M1"]
        # First dep_change on M2: before-state was empty.
        assert dep_rows[0]["dependsOnDisplayBefore"] == []

    def test_milestone_dep_change_records_old_and_new_on_replace(
        self, client, admin_headers, project_via_api,
    ):
        """When a dep is replaced rather than added from empty, both
        before and after labels are present on the dep_change row."""
        m1 = client.post(
            f"/api/v3/projects/{project_via_api['id']}/milestones/create",
            headers=admin_headers,
            json={"name": "First",
                  "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                  "priority": "p1"},
        ).json()["data"]
        m2 = client.post(
            f"/api/v3/projects/{project_via_api['id']}/milestones/create",
            headers=admin_headers,
            json={"name": "Second",
                  "startDate": _iso(2026, 7, 15), "endDate": _iso(2026, 7, 25),
                  "priority": "p1"},
        ).json()["data"]
        m3 = client.post(
            f"/api/v3/projects/{project_via_api['id']}/milestones/create",
            headers=admin_headers,
            json={"name": "Third",
                  "startDate": _iso(2026, 7, 30), "endDate": _iso(2026, 8, 30),
                  "priority": "p1"},
        ).json()["data"]
        # M3 depends on M1.
        assert client.patch(
            f"/api/v3/milestones/{m3['id']}", headers=admin_headers,
            json={"dependsOn": [m1["id"]]},
        ).status_code == 200
        # Now swap: M3 depends on M2 instead.
        assert client.patch(
            f"/api/v3/milestones/{m3['id']}", headers=admin_headers,
            json={"dependsOn": [m2["id"]]},
        ).status_code == 200

        rows = client.get(
            f"/api/v3/projects/{project_via_api['id']}/audit-logs",
            headers=admin_headers,
        ).json()["data"]["_embedded"]["elements"]
        m3_dep_rows = [
            r for r in rows
            if r["action"] == "milestone.dep_change" and r["code"] == "M3"
        ]
        # Newest first by id desc — the second swap is at index 0.
        latest = m3_dep_rows[0]
        assert latest["dependsOnDisplay"] == ["M2"]
        assert latest["dependsOnDisplayBefore"] == ["M1"]
        # The first dep_change recorded empty → M1.
        first = m3_dep_rows[-1]
        assert first["dependsOnDisplay"] == ["M1"]
        assert first["dependsOnDisplayBefore"] == []


class TestUpdateRowsHaveNullDeps:
    def test_update_row_dependsondisplay_is_null(
        self, client, admin_headers, project_via_api,
    ):
        """A regular *.update row (no dep change) should report
        dependsOnDisplay = null and dependsOnDisplayBefore = null —
        deps weren't part of that row's payload."""
        m = client.post(
            f"/api/v3/projects/{project_via_api['id']}/milestones/create",
            headers=admin_headers,
            json={"name": "Updatable",
                  "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 30),
                  "priority": "p1"},
        ).json()["data"]
        # Rename — this is a pure milestone.update, no dep_change.
        assert client.patch(
            f"/api/v3/milestones/{m['id']}", headers=admin_headers,
            json={"name": "Renamed"},
        ).status_code == 200

        rows = client.get(
            f"/api/v3/projects/{project_via_api['id']}/audit-logs",
            headers=admin_headers,
        ).json()["data"]["_embedded"]["elements"]
        upd = next(
            r for r in rows
            if r["action"] == "milestone.update" and r["code"] == "M1"
        )
        assert upd["dependsOnDisplay"] is None
        assert upd["dependsOnDisplayBefore"] is None


class TestOriginalLogsPreserved:
    def test_before_and_after_json_pass_through_unchanged(
        self, client, admin_headers, project_via_api, db_session,
    ):
        """Verify the raw ``before`` / ``after`` JSON in the response is
        byte-equivalent to what record_audit wrote — the new
        ``code`` / ``dependsOnDisplay`` fields are additive only."""
        m = client.post(
            f"/api/v3/projects/{project_via_api['id']}/milestones/create",
            headers=admin_headers,
            json={
                "name": "Plain M",
                "startDate": _iso(2026, 7, 1),
                "endDate": _iso(2026, 8, 1),
                "priority": "p1",
            },
        ).json()["data"]
        # Pull the row directly from the DB to compare.
        row = (
            db_session.query(ProjectAuditLogModel)
            .filter(ProjectAuditLogModel.project_id == project_via_api["id"])
            .filter(ProjectAuditLogModel.action == "milestone.create")
            .first()
        )
        assert row is not None
        raw_before = row.before
        raw_after = row.after

        resp = client.get(
            f"/api/v3/projects/{project_via_api['id']}/audit-logs",
            headers=admin_headers,
        )
        rows = resp.json()["data"]["_embedded"]["elements"]
        ms_row = next(x for x in rows if x["id"] == row.id)
        # UUIDs / fields in the raw JSON come back identical.
        assert ms_row["before"] == raw_before
        assert ms_row["after"] == raw_after
        # And the new readability fields are present alongside.
        assert "code" in ms_row
        assert "dependsOnDisplay" in ms_row
        assert "dependsOnDisplayBefore" in ms_row


class TestHardDeletedEntityFallsThrough:
    def test_orphan_milestone_id_returns_null_code(
        self, client, admin_headers, project_via_api, db_session,
    ):
        # Manually plant an audit row pointing at a milestone_id that
        # doesn't exist (simulates a hard-deleted milestone — the
        # historical row stays but the entity is gone).
        ghost_id = str(uuid4())
        db_session.add(ProjectAuditLogModel(
            project_id=project_via_api["id"],
            actor_id=None, actor_login="system", actor_code="system",
            actor_role="system",
            project_name=project_via_api["name"],
            project_status="published", owner="tmd1",
            action="milestone.soft_delete",
            before={"milestone_id": ghost_id, "name": "Ghost"},
            after=None,
        ))
        db_session.commit()
        r = client.get(
            f"/api/v3/projects/{project_via_api['id']}/audit-logs",
            headers=admin_headers,
        )
        rows = r.json()["data"]["_embedded"]["elements"]
        ghost_row = next(
            x for x in rows
            if x["action"] == "milestone.soft_delete"
            and (x.get("before") or {}).get("milestone_id") == ghost_id
        )
        # Hard-deleted (or never-existed) entity → code null.
        assert ghost_row["code"] is None


@pytest.fixture
def vendor_id(client, admin_headers):
    v = client.post(
        "/api/v3/vendors/create",
        headers=admin_headers,
        json={"name": f"Asg V {uuid4().hex[:4]}",
              "phoneNumber": "+919999999999"},
    ).json()["data"]
    return v["id"]


def _build_chain(client, admin_headers, project_id, vendor_id):
    """Build a single M -> A -> T chain matching the project-service
    activity create contract (ownerDivision + vendorId + concernedDivision
    required). Tasks/subtasks need the project to be published, so
    publish before adding the task."""
    client.patch(
        f"/api/v3/projects/{project_id}", headers=admin_headers,
        json={"vendorIds": [vendor_id]},
    )
    m = client.post(
        f"/api/v3/projects/{project_id}/milestones/create",
        headers=admin_headers,
        json={"name": "M", "priority": "p1",
              "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30)},
    ).json()["data"]
    a = client.post(
        f"/api/v3/milestones/{m['id']}/activities/create",
        headers=admin_headers,
        json={"name": "A", "priority": "p1",
              "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 30),
              "ownerDivision": "tmd1", "vendorId": vendor_id,
              "concernedDivision": ["tmd1"]},
    ).json()["data"]
    pub = client.post(
        f"/api/v3/projects/{project_id}/publish", headers=admin_headers,
    )
    assert pub.status_code in (200, 201), pub.text
    t = client.post(
        f"/api/v3/activities/{a['id']}/tasks/create",
        headers=admin_headers,
        json={"name": "T", "priority": "p1",
              "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 15)},
    ).json()["data"]
    return m, a, t


class TestTaskAuditCoverage:
    """Doc 54 part 2: tasks/services/update.py now fires record_audit
    on field updates AND on dep changes — previously silent."""

    def test_task_field_update_writes_audit_row(
        self, client, admin_headers, project_via_api, vendor_id, db_session,
    ):
        _, _, t = _build_chain(
            client, admin_headers, project_via_api["id"], vendor_id,
        )
        # Rename — pure task.update.
        r = client.patch(
            f"/api/v3/tasks/{t['id']}", headers=admin_headers,
            json={"name": "T Renamed"},
        )
        assert r.status_code == 200, r.text

        row = (
            db_session.query(ProjectAuditLogModel)
            .filter(ProjectAuditLogModel.project_id == project_via_api["id"])
            .filter(ProjectAuditLogModel.action == "task.update")
            .first()
        )
        assert row is not None
        assert (row.after or {}).get("name") == "T Renamed"

    def test_subtask_dep_change_writes_audit_row(
        self, client, admin_headers, project_via_api, vendor_id, db_session,
    ):
        _, _, t = _build_chain(
            client, admin_headers, project_via_api["id"], vendor_id,
        )
        s1 = client.post(
            f"/api/v3/tasks/{t['id']}/subtasks/create",
            headers=admin_headers,
            json={"name": "S1", "priority": "p1",
                  "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 5)},
        ).json()["data"]
        s2 = client.post(
            f"/api/v3/tasks/{t['id']}/subtasks/create",
            headers=admin_headers,
            json={"name": "S2", "priority": "p1",
                  "startDate": _iso(2026, 7, 6), "endDate": _iso(2026, 7, 10)},
        ).json()["data"]
        # S2 depends on S1 — fires subtask.dep_change.
        r = client.patch(
            f"/api/v3/subtasks/{s2['id']}", headers=admin_headers,
            json={"dependsOn": [s1["id"]]},
        )
        assert r.status_code == 200, r.text

        row = (
            db_session.query(ProjectAuditLogModel)
            .filter(ProjectAuditLogModel.project_id == project_via_api["id"])
            .filter(ProjectAuditLogModel.action == "subtask.dep_change")
            .first()
        )
        assert row is not None
        assert (row.before or {}).get("depends_on") == []
        assert (row.after or {}).get("depends_on") == [s1["id"]]
