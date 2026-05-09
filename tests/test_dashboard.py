"""Integration tests for the ``/api/v3/dashboard/*`` surface.

Coverage map (one or more tests per row below):

  ┌─ Access control ──────────────────────────────────────────────┐
  │ - Anonymous → 401                                             │
  │ - Non-admin (member) → 403                                    │
  │ - Admin → 200                                                 │
  └────────────────────────────────────────────────────────────────┘

  ┌─ Bucket derivation (the locked spec) ─────────────────────────┐
  │ - closed lifecycle → completed                                │
  │ - new + no items → ontrack (vacuous truth)                    │
  │ - published + every item ontrack → ontrack                    │
  │ - published + any item past end → delayed                     │
  │ - completed item past end → still completed (item rule)       │
  └────────────────────────────────────────────────────────────────┘

  ┌─ Endpoint shapes ─────────────────────────────────────────────┐
  │ - /summary: counts + top org/division + delayed track         │
  │ - /projects: filters (bucket / q / vendor / division) + page  │
  │ - /projects/{id}: KPIs + pie + delayed track                  │
  │ - /projects/{id}/items: kind / bucket / milestoneId / minDelay│
  │ - /organisations: vendor pie + cards                          │
  │ - /organisations/{id}: project list + bucket counts           │
  └────────────────────────────────────────────────────────────────┘
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.infrastructure.db.models.activity import ActivityModel
from app.infrastructure.db.models.milestone import MilestoneModel
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.project_vendor import ProjectVendorModel
from app.infrastructure.db.models.vendor import VendorModel


# ---------------------------------------------------------------------------
# Helpers — write rows directly via the session for fast deterministic setup.
# Going through the create endpoints would force us to walk the publish gate,
# date validations, etc. — none of which are what we're testing here.
# ---------------------------------------------------------------------------

def _utc(y, m, d):
    return datetime(y, m, d, 0, 0, 0, tzinfo=timezone.utc)


def _make_project(
    db, *, name, status="published", owner="tmd1",
    start=None, end=None, code=None,
):
    p = ProjectModel(
        id=str(uuid4()),
        project_code=code or f"UIDAI-PR{uuid4().hex[:10]}",
        name=name,
        description=f"{name} description",
        status=status,
        owner=owner,
        start_date=start or _utc(2026, 1, 1),
        end_date=end or _utc(2026, 12, 31),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_vendor(db, *, name, active=True):
    v = VendorModel(
        id=str(uuid4()),
        vendor_code=f"VN-{uuid4().hex[:8]}",
        name=name,
        active=active,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def _attach_vendor(db, *, project_id, vendor_id):
    db.add(ProjectVendorModel(project_id=project_id, vendor_id=vendor_id))
    db.commit()


def _next_position(db, model, *, filter_kwargs):
    """Auto-pick the next ``position`` for a row scoped by
    ``filter_kwargs``. Avoids hard-coding ``position=0`` collisions
    against the unique index that gates milestones / activities per
    parent. Live rows only (``deleted_at IS NULL``)."""
    q = db.query(model)
    for k, v in filter_kwargs.items():
        q = q.filter(getattr(model, k) == v)
    q = q.filter(model.deleted_at.is_(None))
    existing = [r.position for r in q.all()]
    return (max(existing) + 1) if existing else 0


def _make_milestone(
    db, *, project_id, name, start, end, status="not_completed", position=None,
):
    if position is None:
        position = _next_position(
            db, MilestoneModel, filter_kwargs={"project_id": project_id},
        )
    m = MilestoneModel(
        id=str(uuid4()),
        project_id=project_id,
        name=name,
        position=position,
        start_date=start,
        end_date=end,
        status=status,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _make_activity(
    db, *, project_id, milestone_id, name, start, end,
    status="not_completed", position=None,
):
    if position is None:
        position = _next_position(
            db, ActivityModel, filter_kwargs={"milestone_id": milestone_id},
        )
    a = ActivityModel(
        id=str(uuid4()),
        project_id=project_id,
        milestone_id=milestone_id,
        name=name,
        position=position,
        start_date=start,
        end_date=end,
        status=status,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

class TestAccessControl:
    def test_anonymous_summary_is_401(self, client):
        r = client.get("/api/v3/dashboard/summary")
        assert r.status_code == 401, r.text

    def test_member_summary_is_403(self, client, member_headers):
        r = client.get(
            "/api/v3/dashboard/summary", headers=member_headers,
        )
        assert r.status_code == 403, r.text

    def test_admin_summary_is_200(self, client, admin_headers):
        r = client.get(
            "/api/v3/dashboard/summary", headers=admin_headers,
        )
        assert r.status_code == 200, r.text

    def test_member_projects_is_403(self, client, member_headers):
        r = client.get(
            "/api/v3/dashboard/projects", headers=member_headers,
        )
        assert r.status_code == 403, r.text

    def test_member_organisations_is_403(self, client, member_headers):
        r = client.get(
            "/api/v3/dashboard/organisations", headers=member_headers,
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_empty_database_zero_counts(self, client, admin_headers):
        r = client.get(
            "/api/v3/dashboard/summary", headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["counts"] == {
            "total": 0, "ontrack": 0, "delayed": 0, "completed": 0,
        }
        assert data["delayedTrack"] == []
        assert data["topOrganisations"] == []
        assert data["topDivisions"] == []
        # asOf is an IST calendar date string (YYYY-MM-DD).
        assert len(data["asOf"]) == 10

    def test_buckets_for_closed_new_published_delayed(
        self, client, admin_headers, db_session,
    ):
        # closed → completed
        _make_project(db_session, name="P-closed", status="closed")
        # new + no items → ontrack (vacuous truth)
        _make_project(db_session, name="P-new", status="new")
        # published + all items in future → ontrack
        p_ok = _make_project(
            db_session, name="P-ok", status="published",
        )
        m_ok = _make_milestone(
            db_session, project_id=p_ok.id, name="M-ok",
            start=_utc(2099, 1, 1), end=_utc(2099, 12, 31),
        )
        _make_activity(
            db_session, project_id=p_ok.id, milestone_id=m_ok.id,
            name="A-ok", start=_utc(2099, 1, 1), end=_utc(2099, 6, 30),
        )
        # published + a milestone past end (1990) → delayed
        p_late = _make_project(
            db_session, name="P-late", status="published",
        )
        _make_milestone(
            db_session, project_id=p_late.id, name="M-late",
            start=_utc(1990, 1, 1), end=_utc(1990, 6, 30),
        )

        r = client.get(
            "/api/v3/dashboard/summary", headers=admin_headers,
        )
        data = r.json()["data"]
        assert data["counts"]["completed"] == 1
        assert data["counts"]["ontrack"] == 2
        assert data["counts"]["delayed"] == 1
        assert data["counts"]["total"] == 4

    def test_completed_item_past_end_stays_completed(
        self, client, admin_headers, db_session,
    ):
        """Item bucket: ``status=completed`` wins even if past end date.
        The project then has zero ``delayed`` items and lands ``ontrack``.
        """
        p = _make_project(
            db_session, name="P-finished-late", status="published",
        )
        m = _make_milestone(
            db_session, project_id=p.id, name="M-done-late",
            start=_utc(1990, 1, 1), end=_utc(1990, 6, 30),
            status="completed",
        )
        _make_activity(
            db_session, project_id=p.id, milestone_id=m.id, name="A-done-late",
            start=_utc(1990, 1, 1), end=_utc(1990, 6, 30),
            status="completed",
        )
        r = client.get(
            "/api/v3/dashboard/summary", headers=admin_headers,
        )
        data = r.json()["data"]
        assert data["counts"]["ontrack"] == 1
        assert data["counts"]["delayed"] == 0
        assert data["counts"]["completed"] == 0

    def test_delayed_track_grouping_and_filter(
        self, client, admin_headers, db_session,
    ):
        # Project with two delayed milestones (both 90 days late).
        p = _make_project(
            db_session, name="P-with-delays", status="published",
        )
        _make_milestone(
            db_session, project_id=p.id, name="M1",
            start=_utc(1990, 1, 1), end=_utc(1990, 6, 30), position=1,
        )
        _make_milestone(
            db_session, project_id=p.id, name="M2",
            start=_utc(1990, 1, 1), end=_utc(1990, 6, 30), position=2,
        )
        r = client.get(
            "/api/v3/dashboard/summary?delayMinDays=10",
            headers=admin_headers,
        )
        data = r.json()["data"]
        assert len(data["delayedTrack"]) == 1
        row = data["delayedTrack"][0]
        assert row["delayedItemCount"] == 2
        assert row["maxDelayDays"] >= 30  # very large since end is 1990

    def test_top_organisation_and_division_cards(
        self, client, admin_headers, db_session,
    ):
        v_a = _make_vendor(db_session, name="VendorA")
        v_b = _make_vendor(db_session, name="VendorB")
        # 3 projects with VendorA, 1 with VendorB.
        for i in range(3):
            p = _make_project(
                db_session, name=f"PA-{i}", status="published", owner="tmd1",
            )
            _attach_vendor(
                db_session, project_id=p.id, vendor_id=v_a.id,
            )
        p_b = _make_project(
            db_session, name="PB", status="published", owner="tmd2",
        )
        _attach_vendor(db_session, project_id=p_b.id, vendor_id=v_b.id)

        r = client.get(
            "/api/v3/dashboard/summary", headers=admin_headers,
        )
        data = r.json()["data"]
        org_names = [o["name"] for o in data["topOrganisations"]]
        # VendorA must rank first (3 projects vs 1).
        assert org_names[0] == "VendorA"
        # Divisions: tmd1 (3) leads tmd2 (1).
        div_codes = [d["code"] for d in data["topDivisions"]]
        assert div_codes[0] == "tmd1"


# ---------------------------------------------------------------------------
# /projects (listing with filters)
# ---------------------------------------------------------------------------

class TestProjectsList:
    def test_pagination_and_search(self, client, admin_headers, db_session):
        for i in range(5):
            _make_project(
                db_session, name=f"Alpha-{i}", status="published",
            )
        _make_project(db_session, name="Bravo", status="published")
        r = client.get(
            "/api/v3/dashboard/projects?q=Alpha&page=1&pageSize=2",
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["total"] == 5
        assert len(data["projects"]) == 2
        # All matched names start with "Alpha".
        assert all(p["name"].startswith("Alpha") for p in data["projects"])

    def test_bucket_filter_active_excludes_completed(
        self, client, admin_headers, db_session,
    ):
        _make_project(db_session, name="Done", status="closed")
        _make_project(db_session, name="Live", status="published")
        r = client.get(
            "/api/v3/dashboard/projects?bucket=active",
            headers=admin_headers,
        )
        names = [p["name"] for p in r.json()["data"]["projects"]]
        assert "Live" in names
        assert "Done" not in names

    def test_vendor_filter(self, client, admin_headers, db_session):
        v = _make_vendor(db_session, name="VOnly")
        p = _make_project(db_session, name="HasV", status="published")
        _attach_vendor(db_session, project_id=p.id, vendor_id=v.id)
        _make_project(db_session, name="NoV", status="published")
        r = client.get(
            f"/api/v3/dashboard/projects?vendorId={v.id}",
            headers=admin_headers,
        )
        names = [p["name"] for p in r.json()["data"]["projects"]]
        assert names == ["HasV"]

    def test_division_filter(self, client, admin_headers, db_session):
        _make_project(
            db_session, name="P-tmd2", status="published", owner="tmd2",
        )
        _make_project(
            db_session, name="P-tmd1", status="published", owner="tmd1",
        )
        r = client.get(
            "/api/v3/dashboard/projects?division=tmd2",
            headers=admin_headers,
        )
        names = [p["name"] for p in r.json()["data"]["projects"]]
        assert names == ["P-tmd2"]


# ---------------------------------------------------------------------------
# /projects/{id} — Project View
# ---------------------------------------------------------------------------

class TestProjectDetail:
    def test_404_on_unknown_project(self, client, admin_headers):
        r = client.get(
            "/api/v3/dashboard/projects/no-such-id",
            headers=admin_headers,
        )
        assert r.status_code == 404, r.text

    def test_kpis_and_pie_for_mixed_items(
        self, client, admin_headers, db_session,
    ):
        # 2 milestones (1 completed, 1 delayed); 3 activities (1 completed, 2 ontrack).
        p = _make_project(db_session, name="Mix", status="published")
        m1 = _make_milestone(
            db_session, project_id=p.id, name="M1",
            start=_utc(2099, 1, 1), end=_utc(2099, 6, 30),
            status="completed", position=1,
        )
        m2 = _make_milestone(
            db_session, project_id=p.id, name="M2",
            start=_utc(1990, 1, 1), end=_utc(1990, 6, 30),
            status="not_completed", position=2,
        )
        _make_activity(
            db_session, project_id=p.id, milestone_id=m1.id, name="A1-done",
            start=_utc(2099, 1, 1), end=_utc(2099, 2, 1),
            status="completed",
        )
        _make_activity(
            db_session, project_id=p.id, milestone_id=m1.id, name="A2-live",
            start=_utc(2099, 1, 1), end=_utc(2099, 2, 1),
        )
        _make_activity(
            db_session, project_id=p.id, milestone_id=m2.id, name="A3-live",
            start=_utc(2099, 1, 1), end=_utc(2099, 2, 1),
        )
        r = client.get(
            f"/api/v3/dashboard/projects/{p.id}", headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        kpi = data["kpis"]
        assert kpi["milestonesTotal"] == 2
        assert kpi["milestonesCompleted"] == 1
        assert kpi["milestonesDelayed"] == 1
        assert kpi["milestonesOntrack"] == 0
        assert kpi["activitiesTotal"] == 3
        assert kpi["activitiesCompleted"] == 1
        assert kpi["activitiesDelayed"] == 0
        assert kpi["activitiesOntrack"] == 2
        # progress = (completedM + completedA)/(totalM + totalA) = 2/5 = 40%
        assert kpi["progressPct"] == 40
        # Pending approvals — static 0 in v1.
        assert kpi["pendingApprovals"] == 0
        # Pie of M+A items: 2 completed, 1 delayed, 2 ontrack, 5 total.
        assert data["pie"] == {
            "total": 5, "completed": 2, "delayed": 1, "ontrack": 2,
        }
        # Project bucket: any delayed item → delayed.
        assert data["project"]["bucket"] == "delayed"

    def test_delayed_track_includes_only_above_floor(
        self, client, admin_headers, db_session,
    ):
        p = _make_project(db_session, name="Floor", status="published")
        # End of 1990 → many years late — definitely above any reasonable floor.
        _make_milestone(
            db_session, project_id=p.id, name="M-very-late",
            start=_utc(1990, 1, 1), end=_utc(1990, 6, 30),
        )
        # End yesterday — delay = 1 day.
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        _make_milestone(
            db_session, project_id=p.id, name="M-1day-late",
            start=_utc(2026, 1, 1), end=yesterday, position=2,
        )
        r = client.get(
            f"/api/v3/dashboard/projects/{p.id}?delayMinDays=10",
            headers=admin_headers,
        )
        data = r.json()["data"]
        names = [row["name"] for row in data["delayedTrack"]]
        assert "M-very-late" in names
        assert "M-1day-late" not in names


# ---------------------------------------------------------------------------
# /projects/{id}/items — drill-down
# ---------------------------------------------------------------------------

class TestProjectItems:
    def test_kind_filter_and_milestone_id(
        self, client, admin_headers, db_session,
    ):
        p = _make_project(db_session, name="Drill", status="published")
        m1 = _make_milestone(
            db_session, project_id=p.id, name="M1",
            start=_utc(2099, 1, 1), end=_utc(2099, 6, 30), position=1,
        )
        m2 = _make_milestone(
            db_session, project_id=p.id, name="M2",
            start=_utc(2099, 1, 1), end=_utc(2099, 6, 30), position=2,
        )
        _make_activity(
            db_session, project_id=p.id, milestone_id=m1.id,
            name="A-under-M1", start=_utc(2099, 1, 1), end=_utc(2099, 2, 1),
        )
        _make_activity(
            db_session, project_id=p.id, milestone_id=m2.id,
            name="A-under-M2", start=_utc(2099, 1, 1), end=_utc(2099, 2, 1),
        )

        # kind=milestone → only the two milestones.
        r1 = client.get(
            f"/api/v3/dashboard/projects/{p.id}/items?kind=milestone",
            headers=admin_headers,
        )
        names = [row["name"] for row in r1.json()["data"]["rows"]]
        assert sorted(names) == ["M1", "M2"]

        # milestoneId narrows activities under that milestone.
        r2 = client.get(
            f"/api/v3/dashboard/projects/{p.id}/items"
            f"?kind=activity&milestoneId={m1.id}",
            headers=admin_headers,
        )
        names = [row["name"] for row in r2.json()["data"]["rows"]]
        assert names == ["A-under-M1"]

    def test_bucket_filter(self, client, admin_headers, db_session):
        p = _make_project(db_session, name="Buckets", status="published")
        _make_milestone(
            db_session, project_id=p.id, name="M-late",
            start=_utc(1990, 1, 1), end=_utc(1990, 6, 30), position=1,
        )
        _make_milestone(
            db_session, project_id=p.id, name="M-future",
            start=_utc(2099, 1, 1), end=_utc(2099, 6, 30), position=2,
        )
        r = client.get(
            f"/api/v3/dashboard/projects/{p.id}/items?bucket=delayed",
            headers=admin_headers,
        )
        names = [row["name"] for row in r.json()["data"]["rows"]]
        assert names == ["M-late"]


# ---------------------------------------------------------------------------
# /organisations
# ---------------------------------------------------------------------------

class TestOrganisations:
    def test_vendor_pie_active_inactive(
        self, client, admin_headers, db_session,
    ):
        _make_vendor(db_session, name="Va", active=True)
        _make_vendor(db_session, name="Vb", active=False)
        _make_vendor(db_session, name="Vc", active=True)
        r = client.get(
            "/api/v3/dashboard/organisations", headers=admin_headers,
        )
        data = r.json()["data"]
        assert data["pie"] == {
            "activeVendors": 2, "inactiveVendors": 1, "total": 3,
        }

    def test_vendor_card_counts_by_bucket(
        self, client, admin_headers, db_session,
    ):
        v = _make_vendor(db_session, name="V")
        # Two projects with V: one ontrack, one delayed.
        p_ok = _make_project(db_session, name="P-ok", status="published")
        _make_milestone(
            db_session, project_id=p_ok.id, name="M-future",
            start=_utc(2099, 1, 1), end=_utc(2099, 6, 30),
        )
        _attach_vendor(
            db_session, project_id=p_ok.id, vendor_id=v.id,
        )
        p_late = _make_project(db_session, name="P-late", status="published")
        _make_milestone(
            db_session, project_id=p_late.id, name="M-past",
            start=_utc(1990, 1, 1), end=_utc(1990, 6, 30),
        )
        _attach_vendor(
            db_session, project_id=p_late.id, vendor_id=v.id,
        )
        r = client.get(
            "/api/v3/dashboard/organisations", headers=admin_headers,
        )
        data = r.json()["data"]
        v_card = next(o for o in data["organisations"] if o["name"] == "V")
        assert v_card["projectCount"] == 2
        assert v_card["counts"]["ontrack"] == 1
        assert v_card["counts"]["delayed"] == 1
        assert v_card["counts"]["completed"] == 0

    def test_vendor_detail(self, client, admin_headers, db_session):
        v = _make_vendor(db_session, name="DetailV")
        p = _make_project(db_session, name="DetailP", status="closed")
        _attach_vendor(db_session, project_id=p.id, vendor_id=v.id)
        # Project with no vendor link should NOT show up in this vendor's
        # detail page.
        _make_project(db_session, name="OtherP", status="published")
        r = client.get(
            f"/api/v3/dashboard/organisations/{v.id}",
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["organisation"]["name"] == "DetailV"
        names = [p["name"] for p in data["projects"]]
        assert names == ["DetailP"]
        assert data["pie"]["completed"] == 1

    def test_vendor_detail_404(self, client, admin_headers):
        r = client.get(
            "/api/v3/dashboard/organisations/missing",
            headers=admin_headers,
        )
        assert r.status_code == 404, r.text
