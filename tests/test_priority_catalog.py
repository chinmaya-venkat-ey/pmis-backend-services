"""Doc 41 — priorities catalog + activity.priority field.

End-to-end coverage of the new feature:

  - GET /api/v3/master/priorities lists the seeded p1/p2/p3.
  - POST /api/v3/master/priorities/create lets admin add p4 etc.
  - PATCH /api/v3/master/priorities/{code} updates name/description.
  - DELETE / restore for non-builtin rows; built-ins refuse.
  - Activity create REQUIRES priority — 422 when omitted.
  - Activity create accepts an admin-added code (p4) once it exists
    in the catalog; rejects unknown codes with 422.
  - Activity PATCH updates priority.
  - Tree response surfaces priority on every activity node.
"""
from uuid import uuid4

import pytest


def _iso(y, m, d):
    return f"{y:04d}-{m:02d}-{d:02d}T00:00:00+05:30"


@pytest.fixture
def _seeded_priorities(db_session):
    """The migration seeds p1/p2/p3, but in-memory tests don't run
    migrations. Insert the rows manually so the catalog has the
    built-ins the tests expect."""
    from app.infrastructure.db.models.priority import PriorityModel
    existing = {
        r.code for r in db_session.query(PriorityModel.code).all()
    }
    seeds = (
        ("p1", "p1", "High priority", 1),
        ("p2", "p2", "Medium priority", 2),
        ("p3", "p3", "Low priority (default)", 3),
    )
    for code, name, desc, pos in seeds:
        if code in existing:
            continue
        db_session.add(PriorityModel(
            id=str(uuid4()), code=code, name=name,
            description=desc, position=pos,
            active=True, is_builtin=True,
        ))
    db_session.commit()


def _setup(client, admin_headers):
    proj = client.post(
        "/api/v3/projects/create",
        headers=admin_headers,
        json={
            "name": f"PrioP {uuid4().hex[:4]}", "owner": "tmd1",
            "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 12, 31),
        },
    ).json()["data"]
    pid = proj["id"]
    v = client.post(
        "/api/v3/vendors/create",
        headers=admin_headers,
        json={"name": f"PrioV {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
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
    return pid, vid, m


# ---------------------------------------------------------------------------
# Master priorities catalog
# ---------------------------------------------------------------------------

class TestPriorityCatalog:
    def test_list_returns_seeded_p1_p2_p3(
        self, client, admin_headers, _seeded_priorities,
    ):
        r = client.get("/api/v3/master/priorities", headers=admin_headers)
        assert r.status_code == 200, r.text
        codes = [
            item["code"]
            for item in r.json()["data"]["_embedded"]["elements"]
        ]
        assert codes == ["p1", "p2", "p3"]

    def test_picker_endpoint_lists_active_priorities(
        self, client, admin_headers, _seeded_priorities,
    ):
        """FE pickers hit ``GET /api/v3/priorities`` — auth-only, no
        MASTER_DATA_VIEW required. Returns the same dataset the master
        list does, in the same order, minus inactive rows."""
        r = client.get("/api/v3/priorities", headers=admin_headers)
        assert r.status_code == 200, r.text
        items = r.json()["data"]["_embedded"]["elements"]
        assert [i["code"] for i in items] == ["p1", "p2", "p3"]
        # Picker payload carries name + description for the dropdown UX.
        for item in items:
            assert "name" in item
            assert "description" in item
            assert "isBuiltin" in item

    def test_get_by_code(self, client, admin_headers, _seeded_priorities):
        r = client.get("/api/v3/master/priorities/p1", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["code"] == "p1"
        assert body["name"] == "p1"
        assert body["isBuiltin"] is True

    def test_admin_can_add_p4(self, client, admin_headers, _seeded_priorities):
        r = client.post(
            "/api/v3/master/priorities/create",
            headers=admin_headers,
            json={"code": "p4", "name": "p4", "description": "Critical", "position": 0},
        )
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["code"] == "p4"
        assert body["isBuiltin"] is False

    def test_patch_updates_name(self, client, admin_headers, _seeded_priorities):
        # Add a non-builtin first so we can edit it (built-ins are
        # editable too, but staying conservative).
        client.post(
            "/api/v3/master/priorities/create",
            headers=admin_headers,
            json={"code": "p9", "name": "p9", "description": "tmp"},
        )
        r = client.patch(
            "/api/v3/master/priorities/p9",
            headers=admin_headers,
            json={"name": "p9-renamed"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == "p9-renamed"

    def test_delete_refuses_builtin(
        self, client, admin_headers, _seeded_priorities,
    ):
        r = client.delete(
            "/api/v3/master/priorities/p1", headers=admin_headers,
        )
        assert r.status_code in (401, 403, 422), r.text  # AuthorizationError
        assert "built-in" in r.text.lower()

    def test_delete_then_restore_non_builtin(
        self, client, admin_headers, _seeded_priorities,
    ):
        client.post(
            "/api/v3/master/priorities/create",
            headers=admin_headers,
            json={"code": "p7", "name": "p7"},
        )
        d = client.delete(
            "/api/v3/master/priorities/p7", headers=admin_headers,
        )
        assert d.status_code == 200
        assert d.json()["data"]["active"] is False

        rs = client.post(
            "/api/v3/master/priorities/p7/restore", headers=admin_headers,
        )
        assert rs.status_code == 200
        assert rs.json()["data"]["active"] is True


# ---------------------------------------------------------------------------
# Activity priority — required on create + validated against catalog
# ---------------------------------------------------------------------------

class TestActivityPriority:
    def test_create_activity_requires_priority(
        self, client, admin_headers, _seeded_priorities,
    ):
        pid, vid, m = _setup(client, admin_headers)
        r = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                # priority deliberately missing
            },
        )
        assert r.status_code == 422, r.text
        # Pydantic flag for the missing required field.
        assert "priority" in r.text.lower()

    def test_create_activity_accepts_seeded_priority(
        self, client, admin_headers, _seeded_priorities,
    ):
        pid, vid, m = _setup(client, admin_headers)
        r = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p2",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["priority"] == "p2"

    def test_create_activity_rejects_unknown_priority(
        self, client, admin_headers, _seeded_priorities,
    ):
        pid, vid, m = _setup(client, admin_headers)
        r = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p99",  # not in catalog
            },
        )
        assert r.status_code == 422, r.text
        assert "priority" in r.text.lower()

    def test_admin_added_priority_is_immediately_accepted(
        self, client, admin_headers, _seeded_priorities,
    ):
        # Admin adds p4.
        client.post(
            "/api/v3/master/priorities/create",
            headers=admin_headers,
            json={"code": "p4", "name": "p4"},
        )
        pid, vid, m = _setup(client, admin_headers)
        r = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p4",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["priority"] == "p4"

    def test_patch_updates_priority(
        self, client, admin_headers, _seeded_priorities,
    ):
        pid, vid, m = _setup(client, admin_headers)
        a = client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p3",
            },
        ).json()["data"]
        assert a["priority"] == "p3"
        r = client.patch(
            f"/api/v3/activities/{a['id']}",
            headers=admin_headers,
            json={"priority": "p1"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["priority"] == "p1"

    def test_tree_response_surfaces_priority(
        self, client, admin_headers, _seeded_priorities,
    ):
        pid, vid, m = _setup(client, admin_headers)
        client.post(
            f"/api/v3/milestones/{m['id']}/activities/create",
            headers=admin_headers,
            json={
                "name": "A1",
                "startDate": _iso(2026, 7, 1), "endDate": _iso(2026, 7, 10),
                "ownerDivision": "tmd1", "vendorId": vid,
                "concernedDivision": ["tmd1"],
                "priority": "p2",
            },
        )
        tree = client.get(
            f"/api/v3/projects/{pid}/tree", headers=admin_headers,
        ).json()["data"]
        m_node = tree["milestones"][0]
        a_node = m_node["activities"][0]
        assert a_node["priority"] == "p2"
