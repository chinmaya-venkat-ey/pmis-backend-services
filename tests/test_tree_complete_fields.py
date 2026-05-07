"""Tree completeness regression — verifies that GET /projects/{id}/tree
returns every field the detail-endpoints emit, including:

  - Milestone: status, dependsOn, dependsOnDisplay
  - Activity: ownerDivision, concernedDivision (now a list), vendorId
  - Task / Subtask: status
  - Subtask nesting: parent's subtasks[] contains child with all the same
    fields, recursively.

End-to-end smoke test: build a project with two milestones, two activities
(one per milestone), a task pair, a subtask pair and a nested grandchild
subtask. Wire up dependencies between the two siblings at every level
(M->M, A->A, T->T, S->S), PATCH status on each row, then call /tree and
assert the response includes every new field.
"""
from uuid import uuid4

from app.api.v3.tree.service import build_project_tree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+05:30"


def _seed_vendor(client, admin_headers, project_id):
    v = client.post(
        "/api/v3/vendors/create",
        headers=admin_headers,
        json={"name": f"TreeV {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
    )
    vid = v.json()["data"]["id"]
    client.patch(
        f"/api/v3/projects/{project_id}",
        headers=admin_headers,
        json={"vendorIds": [vid]},
    )
    return vid


def _create_full_tree(client, admin_headers):
    proj = client.post(
        "/api/v3/projects/create",
        headers=admin_headers,
        json={
            "name": f"Tree P {uuid4().hex[:4]}",
            "owner": "tmd1",
            "startDate": _iso(2026, 7, 1),
            "endDate": _iso(2026, 12, 31),
        },
    )
    assert proj.status_code == 201, proj.text
    pid = proj.json()["data"]["id"]
    vid = _seed_vendor(client, admin_headers, pid)

    # Two milestones so we can wire an M->M dep between them.
    m1 = client.post(
        f"/api/v3/projects/{pid}/milestones/create",
        headers=admin_headers,
        json={"name": "M1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 8, 30)},
    ).json()["data"]
    m2 = client.post(
        f"/api/v3/projects/{pid}/milestones/create",
        headers=admin_headers,
        json={"name": "M2", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 9, 30)},
    ).json()["data"]
    # M2 dependsOn M1 (M2.end > M1.end ✓, M2.start >= M1.start ✓).
    client.patch(
        f"/api/v3/milestones/{m2['id']}",
        headers=admin_headers,
        json={"dependsOn": [m1["id"]], "status": "completed"},
    )
    client.patch(
        f"/api/v3/milestones/{m1['id']}",
        headers=admin_headers,
        json={"status": "not_completed"},
    )

    # Two activities under M1 — A2 dependsOn A1, then patch ownership/status.
    a1 = client.post(
        f"/api/v3/milestones/{m1['id']}/activities/create",
        headers=admin_headers,
        json={
            "name": "A1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 20),
            "ownerDivision": "tmd1", "vendorId": vid, "concernedDivision": ["tmd1"],
        },
    ).json()["data"]
    a2 = client.post(
        f"/api/v3/milestones/{m1['id']}/activities/create",
        headers=admin_headers,
        json={
            "name": "A2", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 25),
            "ownerDivision": "tmd2", "vendorId": vid,
            "concernedDivision": ["tmd1", "others"],
        },
    ).json()["data"]
    # M2 placeholder activity so publish() passes its "every milestone has
    # at least one activity" gate.
    client.post(
        f"/api/v3/milestones/{m2['id']}/activities/create",
        headers=admin_headers,
        json={
            "name": "A_M2", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 9, 20),
            "ownerDivision": "tmd1", "vendorId": vid, "concernedDivision": ["tmd1"],
        },
    )
    client.patch(
        f"/api/v3/activities/{a2['id']}",
        headers=admin_headers,
        json={"dependsOn": [a1["id"]], "status": "not_completed"},
    )

    # Tasks/subtasks need the project to be PUBLISHED first (see
    # app/api/v3/projects/services/publish.py — gate enforced in
    # task / subtask create services).
    pub = client.post(f"/api/v3/projects/{pid}/publish", headers=admin_headers)
    assert pub.status_code in (200, 201), pub.text

    # Two tasks under A1 — T2 dependsOn T1.
    t1_resp = client.post(
        f"/api/v3/activities/{a1['id']}/tasks/create",
        headers=admin_headers,
        json={"name": "T1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10)},
    )
    assert t1_resp.status_code == 201, t1_resp.text
    t1 = t1_resp.json()["data"]
    t2 = client.post(
        f"/api/v3/activities/{a1['id']}/tasks/create",
        headers=admin_headers,
        json={"name": "T2", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 15)},
    ).json()["data"]
    client.patch(
        f"/api/v3/tasks/{t2['id']}",
        headers=admin_headers,
        json={"dependsOn": [t1["id"]], "status": "in_progress"},
    )
    client.patch(
        f"/api/v3/tasks/{t1['id']}",
        headers=admin_headers,
        json={"status": "completed"},
    )

    # Two subtasks under T1 — S2 dependsOn S1, plus a NESTED subtask under S1.
    s1 = client.post(
        f"/api/v3/tasks/{t1['id']}/subtasks/create",
        headers=admin_headers,
        json={"name": "S1", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 5)},
    ).json()["data"]
    s2 = client.post(
        f"/api/v3/tasks/{t1['id']}/subtasks/create",
        headers=admin_headers,
        json={"name": "S2", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 8)},
    ).json()["data"]
    client.patch(
        f"/api/v3/subtasks/{s2['id']}",
        headers=admin_headers,
        json={"dependsOn": [s1["id"]], "status": "completed"},
    )
    nested = client.post(
        f"/api/v3/subtasks/{s1['id']}/subtasks/create",
        headers=admin_headers,
        json={"name": "S1.1 nested", "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 3)},
    ).json()["data"]
    client.patch(
        f"/api/v3/subtasks/{nested['id']}",
        headers=admin_headers,
        json={"status": "in_progress"},
    )
    client.patch(
        f"/api/v3/subtasks/{s1['id']}",
        headers=admin_headers,
        json={"status": "completed"},
    )

    return {
        "pid": pid, "vid": vid,
        "m1": m1, "m2": m2,
        "a1": a1, "a2": a2,
        "t1": t1, "t2": t2,
        "s1": s1, "s2": s2, "nested": nested,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTreeCompleteFields:
    def test_tree_surfaces_all_expected_fields(self, client, admin_headers):
        ids = _create_full_tree(client, admin_headers)
        pid = ids["pid"]

        resp = client.get(f"/api/v3/projects/{pid}/tree", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        tree = resp.json()["data"]

        # All datetime fields on the wire must carry the explicit IST
        # ``+05:30`` offset — the FE picks calendar dates in IST and
        # round-trips them without conversion. UTC ``+00:00`` or naive
        # values are regressions.
        def _assert_ist(value, *, label):
            if value is None:
                return
            assert value.endswith("+05:30"), (
                f"{label}: expected IST suffix +05:30, got {value!r}"
            )

        assert tree["counts"]["milestones"] == 2
        # 3 = A1 + A2 under M1, plus the M2 placeholder needed for publish().
        assert tree["counts"]["activities"] == 3
        assert tree["counts"]["tasks"] == 2
        assert tree["counts"]["subtasks"] == 3  # S1 + S2 + nested

        # ---- Milestone fields ----
        m_by_id = {m["id"]: m for m in tree["milestones"]}
        m1_node = m_by_id[ids["m1"]["id"]]
        m2_node = m_by_id[ids["m2"]["id"]]

        # Mandatory new milestone fields.
        for key in ("status", "dependsOn", "dependsOnDisplay"):
            assert key in m1_node, f"milestone missing {key}"
            assert key in m2_node, f"milestone missing {key}"

        # Tree dates must be IST-suffixed.
        for node in (m1_node, m2_node):
            _assert_ist(node["startDate"], label=f"milestone {node['displayCode']} startDate")
            _assert_ist(node["endDate"],   label=f"milestone {node['displayCode']} endDate")

        assert m1_node["status"] == "not_completed"
        assert m2_node["status"] == "completed"
        assert m2_node["dependsOn"] == [ids["m1"]["id"]]
        assert m2_node["dependsOnDisplay"] == [m1_node["displayCode"]]
        assert m1_node["dependsOn"] == []
        assert m1_node["dependsOnDisplay"] == []

        # ---- Activity fields (under M1) ----
        a_by_id = {a["id"]: a for a in m1_node["activities"]}
        a1_node = a_by_id[ids["a1"]["id"]]
        a2_node = a_by_id[ids["a2"]["id"]]

        for key in (
            "ownerDivision", "concernedDivision",
            "vendorId", "status", "dependsOn", "dependsOnDisplay",
        ):
            assert key in a1_node, f"activity missing {key}"
            assert key in a2_node, f"activity missing {key}"
        # Doc 39: ``concernedDivision`` keyword preserved; the value must
        # now be a list of division codes (was a string before doc 39).
        assert isinstance(a1_node["concernedDivision"], list)

        # Activity dates must be IST-suffixed.
        for node in (a1_node, a2_node):
            _assert_ist(node["startDate"], label=f"activity {node['displayCode']} startDate")
            _assert_ist(node["endDate"],   label=f"activity {node['displayCode']} endDate")

        assert a1_node["ownerDivision"] == "tmd1"
        assert a1_node["vendorId"] == ids["vid"]
        assert a1_node["concernedDivision"] == ["tmd1"]

        assert a2_node["ownerDivision"] == "tmd2"
        assert a2_node["concernedDivision"] == ["tmd1", "others"]
        assert a2_node["dependsOn"] == [ids["a1"]["id"]]
        assert a2_node["dependsOnDisplay"] == [a1_node["displayCode"]]

        # ---- Task fields ----
        t_by_id = {t["id"]: t for t in a1_node["tasks"]}
        t1_node = t_by_id[ids["t1"]["id"]]
        t2_node = t_by_id[ids["t2"]["id"]]
        for node in (t1_node, t2_node):
            _assert_ist(node["startDate"], label=f"task {node['displayCode']} startDate")
            _assert_ist(node["endDate"],   label=f"task {node['displayCode']} endDate")

        assert "status" in t1_node and "status" in t2_node
        assert t1_node["status"] == "completed"
        assert t2_node["status"] == "in_progress"
        assert t2_node["dependsOn"] == [ids["t1"]["id"]]
        assert t2_node["dependsOnDisplay"] == [t1_node["displayCode"]]

        # ---- Subtask fields (top level under T1) ----
        s_by_id = {s["id"]: s for s in t1_node["subtasks"]}
        s1_node = s_by_id[ids["s1"]["id"]]
        s2_node = s_by_id[ids["s2"]["id"]]
        for node in (s1_node, s2_node):
            _assert_ist(node["startDate"], label=f"subtask {node['displayCode']} startDate")
            _assert_ist(node["endDate"],   label=f"subtask {node['displayCode']} endDate")

        assert "status" in s1_node and "status" in s2_node
        assert s1_node["status"] == "completed"
        assert s2_node["status"] == "completed"
        assert s2_node["dependsOn"] == [ids["s1"]["id"]]
        assert s2_node["dependsOnDisplay"] == [s1_node["displayCode"]]

        # ---- Nested subtask under S1 ----
        assert len(s1_node["subtasks"]) == 1
        nested_node = s1_node["subtasks"][0]
        assert nested_node["id"] == ids["nested"]["id"]
        assert nested_node["parentSubtaskId"] == ids["s1"]["id"]
        assert nested_node["status"] == "in_progress"
        _assert_ist(nested_node["startDate"], label="nested subtask startDate")
        _assert_ist(nested_node["endDate"],   label="nested subtask endDate")
        # Same field set as top-level subtasks — recursion intact.
        for key in (
            "status", "dependsOn", "dependsOnDisplay",
            "displayCode", "subtasks",
        ):
            assert key in nested_node, f"nested subtask missing {key}"
        # No grandchildren; empty list still emitted.
        assert nested_node["subtasks"] == []
