"""Daily deadline-digest cron — end-to-end + service-layer tests.

Coverage:
  - secret-auth gate (401 / 503 / 200)
  - find_due_milestones / find_due_activities filtering
  - responsible_user_ids — scope resolution + active filter
  - aggregate_by_user — per-user de-dupe across overlapping roles
  - render_items_html — content + grouping
  - run_daily_digest — empty-state, normal-state, isolation between users
  - skip rules: completed items, closed projects, soft-deleted rows
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.config import settings as _app_settings
from app.db.models.activity import ActivityModel
from app.db.models.milestone import MilestoneModel
from app.db.models.project import ProjectModel
from app.db.models.project_vendor import ProjectVendorModel
from app.db.models.role import RoleModel
from app.db.models.user import UserModel
from app.db.models.user_role_assignment import UserRoleAssignmentModel
from app.db.session import Base, SessionLocal, engine
from app.services.digest_service import (
    DigestItem,
    aggregate_by_user,
    find_due_activities,
    find_due_milestones,
    render_items_html,
    responsible_user_ids,
    run_daily_digest,
)


# Patch settings directly. By the time pytest reaches this file the
# conftest has already cached the settings object — env-var-at-import
# wouldn't take effect.
_app_settings.cron_shared_secret = "test-cron-secret"
_app_settings.frontend_base_url = "https://pmis.test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _CapturingEmailService:
    """Stand-in for EmailService that records every send call."""
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, is_html, cc=None, bcc=None):
        self.sent.append({
            "to": list(to),
            "subject": subject,
            "body": body,
            "is_html": is_html,
        })
        return {
            "success": True,
            "message": "captured",
            "provider": "test",
            "message_id": f"msg-{len(self.sent)}",
        }


def _utc_midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).replace(tzinfo=None)


@pytest.fixture
def db():
    """Fresh DB per test — wipes everything between tests so prior
    rows don't leak into the next case. Re-seeds the built-in
    notification templates so renderer lookups don't fall through
    to the generic fallback."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Re-seed templates so render_email finds project_deadline_digest.
    from app.db.models.notification_template import NotificationTemplateModel
    from app.db.session import _seed_built_in_templates
    seed_session = SessionLocal()
    try:
        _seed_built_in_templates(seed_session, NotificationTemplateModel)
        seed_session.commit()
    finally:
        seed_session.close()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seed_roles(db):
    rows = []
    for name in ("super_admin", "admin", "org_admin", "project_admin", "project_member"):
        r = RoleModel(name=name)
        db.add(r)
        rows.append(r)
    db.commit()
    return {r.name: r for r in rows}


def _new_user(db, *, login, email, status="active"):
    u = UserModel(
        id=str(uuid4()), login=login, email=email,
        first_name=login.capitalize(), last_name="User",
        status=status,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _new_project(db, *, name="P", status="published", deleted=False):
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"PR-{uuid4().hex[:8].upper()}",
        name=name, status=status,
        deleted_at=_utc_midnight(datetime.utcnow()) if deleted else None,
    )
    db.add(p); db.commit(); db.refresh(p)
    return p


def _new_milestone(db, project, *, name, end_in_days, status="not_completed", deleted=False):
    today = datetime.now(timezone.utc).date()
    end_date = _utc_midnight(today + timedelta(days=end_in_days))
    start_date = _utc_midnight(today - timedelta(days=30))
    m = MilestoneModel(
        id=str(uuid4()), project_id=project.id, name=name,
        start_date=start_date, end_date=end_date,
        status=status,
        deleted_at=_utc_midnight(datetime.utcnow()) if deleted else None,
    )
    db.add(m); db.commit(); db.refresh(m)
    return m


def _new_activity(
    db, project, milestone, *, name, end_in_days, status="not_completed",
    deleted=False,
):
    today = datetime.now(timezone.utc).date()
    end_date = _utc_midnight(today + timedelta(days=end_in_days))
    start_date = _utc_midnight(today - timedelta(days=10))
    a = ActivityModel(
        id=str(uuid4()), project_id=project.id, milestone_id=milestone.id,
        name=name, start_date=start_date, end_date=end_date,
        status=status,
        deleted_at=_utc_midnight(datetime.utcnow()) if deleted else None,
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


def _assign(db, user, role, *, project=None, organization=None):
    a = UserRoleAssignmentModel(
        user_id=user.id, role_id=role.id,
        project_id=project.id if project else None,
        organization_id=organization,
    )
    db.add(a); db.commit()
    return a


def _today():
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# 1. find_due_milestones / find_due_activities filtering
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_milestones_in_window_included(self, db, seed_roles):
        project = _new_project(db)
        m_in = _new_milestone(db, project, name="In window", end_in_days=3)
        _new_milestone(db, project, name="Past window", end_in_days=20)
        rows = find_due_milestones(db, _today(), 5)
        ids = {m.id for _, m in rows}
        assert m_in.id in ids
        assert len(rows) == 1

    def test_overdue_milestones_included(self, db, seed_roles):
        project = _new_project(db)
        m_overdue = _new_milestone(db, project, name="Overdue", end_in_days=-3)
        rows = find_due_milestones(db, _today(), 5)
        assert any(m.id == m_overdue.id for _, m in rows)

    def test_completed_milestones_excluded(self, db, seed_roles):
        project = _new_project(db)
        _new_milestone(db, project, name="Done", end_in_days=2, status="completed")
        rows = find_due_milestones(db, _today(), 5)
        assert rows == []

    def test_closed_project_milestones_excluded(self, db, seed_roles):
        project = _new_project(db, status="closed")
        _new_milestone(db, project, name="In closed P", end_in_days=2)
        rows = find_due_milestones(db, _today(), 5)
        assert rows == []

    def test_deleted_project_milestones_excluded(self, db, seed_roles):
        project = _new_project(db, deleted=True)
        _new_milestone(db, project, name="In deleted P", end_in_days=2)
        rows = find_due_milestones(db, _today(), 5)
        assert rows == []

    def test_deleted_milestones_excluded(self, db, seed_roles):
        project = _new_project(db)
        _new_milestone(db, project, name="Deleted", end_in_days=2, deleted=True)
        rows = find_due_milestones(db, _today(), 5)
        assert rows == []

    def test_activities_in_window_included(self, db, seed_roles):
        project = _new_project(db)
        m = _new_milestone(db, project, name="M", end_in_days=10)
        a_in = _new_activity(db, project, m, name="In window", end_in_days=4)
        _new_activity(db, project, m, name="Past window", end_in_days=20)
        rows = find_due_activities(db, _today(), 5)
        ids = {a.id for _, a in rows}
        assert a_in.id in ids
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 2. responsible_user_ids — scope + active filter + de-dupe
# ---------------------------------------------------------------------------

class TestResponsibleUsers:
    def test_project_admin_and_member_scoped_to_project(self, db, seed_roles):
        project = _new_project(db)
        u1 = _new_user(db, login="pa", email="pa@x.com")
        u2 = _new_user(db, login="pm", email="pm@x.com")
        _assign(db, u1, seed_roles["project_admin"], project=project)
        _assign(db, u2, seed_roles["project_member"], project=project)
        # An admin scoped to a DIFFERENT project — must not appear.
        other = _new_project(db, name="Other")
        u3 = _new_user(db, login="other_pa", email="op@x.com")
        _assign(db, u3, seed_roles["project_admin"], project=other)
        ids = set(responsible_user_ids(db, project.id))
        assert ids == {u1.id, u2.id}

    def test_org_admin_via_vendor_mapping(self, db, seed_roles):
        project = _new_project(db)
        vendor_id = str(uuid4())
        db.add(ProjectVendorModel(project_id=project.id, vendor_id=vendor_id))
        db.commit()
        u = _new_user(db, login="oa", email="oa@x.com")
        _assign(db, u, seed_roles["org_admin"], organization=vendor_id)
        ids = set(responsible_user_ids(db, project.id))
        assert u.id in ids

    def test_unscoped_admin_excluded(self, db, seed_roles):
        project = _new_project(db)
        u = _new_user(db, login="g", email="g@x.com")
        _assign(db, u, seed_roles["admin"])  # global, no scope_id
        ids = set(responsible_user_ids(db, project.id))
        assert u.id not in ids

    def test_inactive_user_excluded(self, db, seed_roles):
        project = _new_project(db)
        u = _new_user(db, login="x", email="x@x.com", status="inactive")
        _assign(db, u, seed_roles["project_admin"], project=project)
        ids = set(responsible_user_ids(db, project.id))
        assert u.id not in ids

    def test_multiple_roles_same_user_dedupes(self, db, seed_roles):
        project = _new_project(db)
        vendor_id = str(uuid4())
        db.add(ProjectVendorModel(project_id=project.id, vendor_id=vendor_id))
        db.commit()
        u = _new_user(db, login="multi", email="m@x.com")
        _assign(db, u, seed_roles["project_admin"], project=project)
        _assign(db, u, seed_roles["org_admin"], organization=vendor_id)
        ids = responsible_user_ids(db, project.id)
        # User appears once even though they have two qualifying roles.
        assert ids.count(u.id) == 1


# ---------------------------------------------------------------------------
# 3. aggregate_by_user — items grouped correctly, per-user dedupe
# ---------------------------------------------------------------------------

class TestAggregation:
    def test_user_gets_items_from_all_their_projects(self, db, seed_roles):
        u = _new_user(db, login="u", email="u@x.com")
        p1 = _new_project(db, name="Alpha")
        p2 = _new_project(db, name="Beta")
        _assign(db, u, seed_roles["project_member"], project=p1)
        _assign(db, u, seed_roles["project_admin"], project=p2)
        _new_milestone(db, p1, name="M1", end_in_days=2)
        m2 = _new_milestone(db, p2, name="M2", end_in_days=10)
        _new_activity(db, p2, m2, name="A2", end_in_days=4)

        agg = aggregate_by_user(db, _today(), 5)
        assert set(agg.keys()) == {u.id}
        levels = sorted((i.level, i.item_name) for i in agg[u.id])
        # M1 + A2 in window; M2 is at +10 (out of window).
        assert levels == [("Activity", "A2"), ("Milestone", "M1")]

    def test_user_with_overlapping_roles_sees_item_once(self, db, seed_roles):
        u = _new_user(db, login="u", email="u@x.com")
        project = _new_project(db)
        vendor_id = str(uuid4())
        db.add(ProjectVendorModel(project_id=project.id, vendor_id=vendor_id))
        db.commit()
        _assign(db, u, seed_roles["project_admin"], project=project)
        _assign(db, u, seed_roles["org_admin"], organization=vendor_id)
        _new_milestone(db, project, name="One milestone", end_in_days=1)
        agg = aggregate_by_user(db, _today(), 5)
        assert len(agg[u.id]) == 1

    def test_users_isolated_from_each_other(self, db, seed_roles):
        u1 = _new_user(db, login="u1", email="u1@x.com")
        u2 = _new_user(db, login="u2", email="u2@x.com")
        p1 = _new_project(db, name="Only-U1")
        p2 = _new_project(db, name="Only-U2")
        _assign(db, u1, seed_roles["project_admin"], project=p1)
        _assign(db, u2, seed_roles["project_admin"], project=p2)
        _new_milestone(db, p1, name="MA", end_in_days=2)
        _new_milestone(db, p2, name="MB", end_in_days=2)
        agg = aggregate_by_user(db, _today(), 5)
        names_u1 = {i.item_name for i in agg[u1.id]}
        names_u2 = {i.item_name for i in agg[u2.id]}
        assert names_u1 == {"MA"}
        assert names_u2 == {"MB"}


# ---------------------------------------------------------------------------
# 4. render_items_html — content + grouping
# ---------------------------------------------------------------------------

class TestRendering:
    def test_project_block_includes_name_and_code(self):
        today = _today()
        items = [DigestItem(
            project_id="p1", project_name="Alpha", project_code="PR-ABC123",
            level="Milestone", item_id="m1", item_name="Site survey",
            end_date=today + timedelta(days=3), days_remaining=3,
        )]
        html = render_items_html(items)
        assert "<b>Alpha</b>" in html
        assert "(PR-ABC123)" in html
        assert "Site survey" in html
        assert "due in 3 days" in html

    def test_overdue_phrasing(self):
        today = _today()
        items = [DigestItem(
            project_id="p1", project_name="Beta", project_code="PR-XYZ",
            level="Activity", item_id="a1", item_name="RFP draft",
            end_date=today - timedelta(days=2), days_remaining=-2,
        )]
        html = render_items_html(items)
        assert "past due by 2 days" in html
        assert "RFP draft" in html

    def test_due_today_phrasing(self):
        today = _today()
        items = [DigestItem(
            project_id="p1", project_name="Beta", project_code="PR-XYZ",
            level="Milestone", item_id="m1", item_name="Kickoff",
            end_date=today, days_remaining=0,
        )]
        html = render_items_html(items)
        assert "due today" in html

    def test_no_alarm_styling(self):
        # No warning colours, no exclamation marks, no large headings.
        today = _today()
        items = [DigestItem(
            project_id="p1", project_name="Alpha", project_code="PR-1",
            level="Milestone", item_id="m1", item_name="Critical",
            end_date=today - timedelta(days=10), days_remaining=-10,
        )]
        html = render_items_html(items)
        assert "color:#a40" not in html  # no red alarm
        assert "⚠" not in html
        assert "<h4" not in html
        assert "<h3" not in html

    def test_groups_by_project(self):
        today = _today()
        items = [
            DigestItem(project_id="p1", project_name="Alpha", project_code="PR-1",
                       level="Milestone", item_id="m1", item_name="M1",
                       end_date=today + timedelta(days=1), days_remaining=1),
            DigestItem(project_id="p2", project_name="Beta", project_code="PR-2",
                       level="Activity", item_id="a1", item_name="A1",
                       end_date=today + timedelta(days=2), days_remaining=2),
            DigestItem(project_id="p1", project_name="Alpha", project_code="PR-1",
                       level="Activity", item_id="a2", item_name="A2",
                       end_date=today + timedelta(days=3), days_remaining=3),
        ]
        html = render_items_html(items)
        # Alpha block should appear once, with both M1 + A2 inside.
        assert html.count("<b>Alpha</b>") == 1
        assert html.count("<b>Beta</b>") == 1


# ---------------------------------------------------------------------------
# 5. run_daily_digest — orchestrator
# ---------------------------------------------------------------------------

class TestOrchestrator:
    def test_empty_state_sends_nothing(self, db, seed_roles):
        email = _CapturingEmailService()
        summary = run_daily_digest(db, email, today=_today(), window_days=5)
        assert summary.users_notified == 0
        assert summary.emails_sent == 0
        assert summary.items_aggregated == 0
        assert email.sent == []

    def test_normal_run_sends_one_per_user(self, db, seed_roles):
        u1 = _new_user(db, login="u1", email="u1@x.com")
        u2 = _new_user(db, login="u2", email="u2@x.com")
        p1 = _new_project(db, name="Alpha")
        p2 = _new_project(db, name="Beta")
        _assign(db, u1, seed_roles["project_admin"], project=p1)
        _assign(db, u2, seed_roles["project_member"], project=p2)
        _new_milestone(db, p1, name="MA", end_in_days=3)
        _new_milestone(db, p2, name="MB", end_in_days=1)

        email = _CapturingEmailService()
        summary = run_daily_digest(db, email, today=_today(), window_days=5)
        assert summary.users_notified == 2
        assert summary.emails_sent == 2
        assert summary.items_aggregated == 2
        recipients = {row["to"][0] for row in email.sent}
        assert recipients == {"u1@x.com", "u2@x.com"}

    def test_email_contains_project_name_code_and_item(self, db, seed_roles):
        u = _new_user(db, login="u", email="u@x.com")
        p = _new_project(db, name="Project Alpha")
        _assign(db, u, seed_roles["project_admin"], project=p)
        _new_milestone(db, p, name="Site survey complete", end_in_days=3)
        email = _CapturingEmailService()
        run_daily_digest(db, email, today=_today(), window_days=5)
        assert len(email.sent) == 1
        body = email.sent[0]["body"]
        assert "Project Alpha" in body
        assert p.project_code in body
        assert "Site survey complete" in body
        # Portal URL injected from FRONTEND_BASE_URL.
        assert "https://pmis.test" in body

    def test_user_with_no_items_gets_no_email(self, db, seed_roles):
        u_quiet = _new_user(db, login="q", email="q@x.com")
        p = _new_project(db)
        _assign(db, u_quiet, seed_roles["project_admin"], project=p)
        # No milestones in window.
        _new_milestone(db, p, name="Far future", end_in_days=30)
        email = _CapturingEmailService()
        summary = run_daily_digest(db, email, today=_today(), window_days=5)
        assert summary.users_notified == 0
        assert email.sent == []


# ---------------------------------------------------------------------------
# 6. Cron endpoint — secret-auth gate
# ---------------------------------------------------------------------------

class TestCronEndpoint:
    def test_missing_secret_returns_401(self, client):
        r = client.post("/api/v1/notifications/cron/daily-digest")
        assert r.status_code == 401

    def test_wrong_secret_returns_401(self, client):
        r = client.post(
            "/api/v1/notifications/cron/daily-digest",
            headers={"X-Cron-Secret": "not-the-secret"},
        )
        assert r.status_code == 401

    def test_correct_secret_returns_200_with_summary(self, client, monkeypatch):
        # Patch the email service used by the route. The route uses
        # get_email_service() — TestClient already stubs SMTP via the
        # conftest's monkeypatch, so .send() returns immediately.
        r = client.post(
            "/api/v1/notifications/cron/daily-digest",
            headers={"X-Cron-Secret": "test-cron-secret"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Fresh empty DB run.
        assert "ranAt" in data
        assert "usersNotified" in data
        assert "emailsSent" in data
        assert "emailsFailed" in data
        assert "itemsAggregated" in data
        assert data["usersNotified"] == 0

    def test_disabled_when_secret_unset(self, client, monkeypatch):
        # Override settings to an empty secret in-place; the dependency
        # reads settings.cron_shared_secret on every call.
        from app.config import settings as _settings
        monkeypatch.setattr(_settings, "cron_shared_secret", "")
        r = client.post(
            "/api/v1/notifications/cron/daily-digest",
            headers={"X-Cron-Secret": "anything"},
        )
        assert r.status_code == 503
