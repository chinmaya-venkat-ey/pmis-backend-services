"""Daily deadline-digest cron logic.

Scans the shared ``pmis_db`` for milestones / activities whose
``end_date`` is on or before ``today + DEADLINE_WINDOW_DAYS`` (so up
to ``window_days`` days in the future) OR already past due. Resolves
the users responsible for each affected project (``org_admin`` of the
project's owning vendor(s), ``project_admin`` of the project,
``project_member`` of the project), groups items per user, renders
the per-user HTML block, and dispatches one email per user via the
existing email_service.

Recipient tiers (role names on the ``roles`` table):
  - ``org_admin``       — scope is ``organization_id`` = a vendor mapped to the project
  - ``project_admin``   — scope is ``project_id`` = the project
  - ``project_member``  — scope is ``project_id`` = the project

Items are skipped when:
  - parent project is closed (``status='closed'``) or soft-deleted
  - the milestone / activity itself is soft-deleted
  - the milestone / activity is already ``status='completed'``
  - the recipient user is soft-deleted or non-``active``
  - the recipient user has no email address

The endpoint that drives this lives in ``routes/cron_routes.py``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models.activity import ActivityModel
from ..db.models.milestone import MilestoneModel
from ..db.models.project import ProjectModel
from ..db.models.project_vendor import ProjectVendorModel
from ..db.models.role import RoleModel
from ..db.models.user import UserModel
from ..db.models.user_role_assignment import UserRoleAssignmentModel
from ..services.email_service import EmailService
from ..services.template_service import render_email


logger = logging.getLogger(__name__)


# Recipient roles considered for the per-project notification list.
# Source-of-truth role names in the ``roles`` table.
_RECIPIENT_ROLES: Tuple[str, ...] = (
    "org_admin", "project_admin", "project_member",
)

_TEMPLATE_KIND = "project_deadline_digest"


@dataclass(frozen=True)
class DigestItem:
    """One row to render in a user's email — a single milestone or
    activity nearing or past its end date."""
    project_id: str
    project_name: str
    project_code: str
    level: str          # "Milestone" or "Activity"
    item_id: str
    item_name: str
    end_date: date      # the calendar date the item ends
    days_remaining: int  # positive = future, negative = overdue, 0 = today


@dataclass(frozen=True)
class DigestSummary:
    """Return value of ``run_daily_digest`` — what to surface to the
    DevOps cron caller."""
    ran_at: datetime
    users_notified: int
    emails_sent: int
    emails_failed: int
    items_aggregated: int


# ---------------------------------------------------------------------------
# Item discovery
# ---------------------------------------------------------------------------

def _as_date(d) -> Optional[date]:
    """Coerce a datetime / date / None to a ``date`` — DB columns may
    come back as either depending on driver."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return None


def find_due_milestones(
    db: Session, today: date, window_days: int,
) -> List[Tuple[ProjectModel, MilestoneModel]]:
    """Return ``(project, milestone)`` pairs for every milestone whose
    end_date falls in ``(-inf, today + window_days]``, skipping
    completed milestones / closed-or-deleted projects / deleted rows."""
    cutoff = datetime.combine(
        today + timedelta(days=window_days + 1), datetime.min.time(),
    )
    rows = (
        db.query(MilestoneModel, ProjectModel)
        .join(ProjectModel, ProjectModel.id == MilestoneModel.project_id)
        .filter(MilestoneModel.deleted_at.is_(None))
        .filter(MilestoneModel.status != "completed")
        .filter(MilestoneModel.end_date < cutoff)
        .filter(ProjectModel.deleted_at.is_(None))
        .filter(ProjectModel.status != "closed")
        .all()
    )
    # Reorder tuple so callers see (project, milestone).
    return [(p, m) for (m, p) in rows]


def find_due_activities(
    db: Session, today: date, window_days: int,
) -> List[Tuple[ProjectModel, ActivityModel]]:
    """Same as ``find_due_milestones`` but for activities. ``end_date``
    is nullable on activities — those rows are skipped."""
    cutoff = datetime.combine(
        today + timedelta(days=window_days + 1), datetime.min.time(),
    )
    rows = (
        db.query(ActivityModel, ProjectModel)
        .join(ProjectModel, ProjectModel.id == ActivityModel.project_id)
        .filter(ActivityModel.deleted_at.is_(None))
        .filter(ActivityModel.end_date.is_not(None))
        .filter(or_(ActivityModel.status.is_(None),
                    ActivityModel.status != "completed"))
        .filter(ActivityModel.end_date < cutoff)
        .filter(ProjectModel.deleted_at.is_(None))
        .filter(ProjectModel.status != "closed")
        .all()
    )
    return [(p, a) for (a, p) in rows]


# ---------------------------------------------------------------------------
# Recipient resolution
# ---------------------------------------------------------------------------

def responsible_user_ids(db: Session, project_id: str) -> List[str]:
    """Return distinct active user ids that should receive deadline
    notifications for a given project. Combines:

    - ``project_admin`` / ``project_member`` rows scoped to the project
    - ``org_admin`` rows scoped to any vendor the project is mapped to
    """
    role_id_to_name = dict(
        db.query(RoleModel.id, RoleModel.name)
        .filter(RoleModel.name.in_(_RECIPIENT_ROLES))
        .all()
    )
    if not role_id_to_name:
        return []
    eligible_role_ids = list(role_id_to_name.keys())

    # Vendors mapped to this project — used for org_admin scope match.
    vendor_ids = [
        row[0] for row in
        db.query(ProjectVendorModel.vendor_id)
        .filter(ProjectVendorModel.project_id == project_id)
        .all()
    ]

    q = (
        db.query(UserRoleAssignmentModel.user_id, RoleModel.name)
        .join(RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id)
        .filter(UserRoleAssignmentModel.role_id.in_(eligible_role_ids))
    )

    project_scope_filter = (
        UserRoleAssignmentModel.project_id == project_id
    )
    if vendor_ids:
        org_scope_filter = UserRoleAssignmentModel.organization_id.in_(vendor_ids)
        q = q.filter(or_(project_scope_filter, org_scope_filter))
    else:
        q = q.filter(project_scope_filter)

    user_ids = {row[0] for row in q.all()}
    if not user_ids:
        return []

    # Filter to active, non-deleted users with an email.
    active = (
        db.query(UserModel.id)
        .filter(UserModel.id.in_(user_ids))
        .filter(UserModel.status == "active")
        .filter(UserModel.deleted_at.is_(None))
        .filter(UserModel.email.is_not(None))
        .all()
    )
    return [r[0] for r in active]


# ---------------------------------------------------------------------------
# Per-user aggregation
# ---------------------------------------------------------------------------

def aggregate_by_user(
    db: Session, today: date, window_days: int,
) -> Dict[str, List[DigestItem]]:
    """Build ``{user_id: [DigestItem, ...]}`` covering every milestone /
    activity due in the window, mapped through the per-project
    recipient resolver. Items are de-duped per user — a user holding
    multiple roles on the same project still sees each item once."""
    by_user: Dict[str, List[DigestItem]] = {}
    seen_per_user: Dict[str, set] = {}

    def _add(uid: str, item: DigestItem):
        key = (item.level, item.item_id)
        s = seen_per_user.setdefault(uid, set())
        if key in s:
            return
        s.add(key)
        by_user.setdefault(uid, []).append(item)

    # Cache the recipient list per project so we don't re-query for
    # every milestone/activity on the same project.
    recipients_cache: Dict[str, List[str]] = {}

    def _recipients(project_id: str) -> List[str]:
        if project_id not in recipients_cache:
            recipients_cache[project_id] = responsible_user_ids(db, project_id)
        return recipients_cache[project_id]

    for project, milestone in find_due_milestones(db, today, window_days):
        end_date = _as_date(milestone.end_date)
        if end_date is None:
            continue
        days_remaining = (end_date - today).days
        item = DigestItem(
            project_id=project.id,
            project_name=project.name,
            project_code=project.project_code,
            level="Milestone",
            item_id=milestone.id,
            item_name=milestone.name,
            end_date=end_date,
            days_remaining=days_remaining,
        )
        for uid in _recipients(project.id):
            _add(uid, item)

    for project, activity in find_due_activities(db, today, window_days):
        end_date = _as_date(activity.end_date)
        if end_date is None:
            continue
        days_remaining = (end_date - today).days
        item = DigestItem(
            project_id=project.id,
            project_name=project.name,
            project_code=project.project_code,
            level="Activity",
            item_id=activity.id,
            item_name=activity.name,
            end_date=end_date,
            days_remaining=days_remaining,
        )
        for uid in _recipients(project.id):
            _add(uid, item)

    return by_user


# ---------------------------------------------------------------------------
# Per-user rendering
# ---------------------------------------------------------------------------

def _fmt_date(d: date) -> str:
    return d.strftime("%d %b %Y")


def render_items_html(items: Iterable[DigestItem]) -> str:
    """Build the per-project HTML block that's injected into the
    template body as ``{items_html}``.

    Layout: each project is a single paragraph (project name bold +
    project code in parentheses) followed by a flat ``<ul>`` of the
    items on that project. No alarming styling — past-due items just
    read "past due by N days" inline.
    """
    # Group by project.
    by_project: Dict[str, List[DigestItem]] = {}
    project_order: List[str] = []
    project_meta: Dict[str, Tuple[str, str]] = {}
    for it in items:
        if it.project_id not in by_project:
            project_order.append(it.project_id)
            project_meta[it.project_id] = (it.project_name, it.project_code)
            by_project[it.project_id] = []
        by_project[it.project_id].append(it)

    blocks: List[str] = []
    for pid in project_order:
        project_name, project_code = project_meta[pid]
        block_lines: List[str] = [
            f"<p style=\"margin-top:12px; margin-bottom:4px;\">"
            f"<b>{project_name}</b> ({project_code})</p>",
            "<ul style=\"margin:0 0 0 20px; padding:0;\">",
        ]
        # Sort: overdue first (oldest first), then by end_date ascending.
        rows = sorted(
            by_project[pid],
            key=lambda x: (x.days_remaining < 0 and -1, x.days_remaining),
        )
        # The above sort tuple isn't quite right — re-sort cleanly:
        rows = sorted(by_project[pid], key=lambda x: x.days_remaining)
        for it in rows:
            block_lines.append(_render_item_line(it))
        block_lines.append("</ul>")
        blocks.append("\n".join(block_lines))
    return "\n".join(blocks)


def _render_item_line(it: DigestItem) -> str:
    if it.days_remaining < 0:
        days = abs(it.days_remaining)
        word = "day" if days == 1 else "days"
        return (
            f"  <li>{it.level} &quot;{it.item_name}&quot; — "
            f"past due by {days} {word} ({_fmt_date(it.end_date)})</li>"
        )
    if it.days_remaining == 0:
        return (
            f"  <li>{it.level} &quot;{it.item_name}&quot; — "
            f"due today ({_fmt_date(it.end_date)})</li>"
        )
    word = "day" if it.days_remaining == 1 else "days"
    return (
        f"  <li>{it.level} &quot;{it.item_name}&quot; — "
        f"due in {it.days_remaining} {word} ({_fmt_date(it.end_date)})</li>"
    )


# ---------------------------------------------------------------------------
# Orchestrator — called by the cron endpoint
# ---------------------------------------------------------------------------

def _portal_url() -> str:
    return (settings.frontend_base_url or "").rstrip("/")


def run_daily_digest(
    db: Session, email_service: EmailService,
    today: Optional[date] = None,
    window_days: Optional[int] = None,
) -> DigestSummary:
    """Top-level entry point — scan, group, render, send. Returns a
    summary the cron endpoint surfaces to its caller."""
    ran_at = datetime.now(timezone.utc)
    today = today or ran_at.date()
    window_days = window_days if window_days is not None else int(
        settings.deadline_window_days
    )

    by_user = aggregate_by_user(db, today, window_days)
    items_aggregated = sum(len(items) for items in by_user.values())

    if not by_user:
        logger.info(
            "daily-digest: nothing to send (no qualifying items).",
        )
        return DigestSummary(
            ran_at=ran_at, users_notified=0, emails_sent=0,
            emails_failed=0, items_aggregated=0,
        )

    users = (
        db.query(UserModel)
        .filter(UserModel.id.in_(list(by_user.keys())))
        .all()
    )
    by_id = {u.id: u for u in users}

    emails_sent = 0
    emails_failed = 0
    users_notified = 0
    portal_url = _portal_url()

    for user_id, items in by_user.items():
        user = by_id.get(user_id)
        if user is None or not user.email:
            continue
        payload = {
            "first_name": (user.first_name or user.login or "there"),
            "items_html": render_items_html(items),
            "portal_url": portal_url,
        }
        try:
            subject, body, is_html = render_email(db, _TEMPLATE_KIND, payload)
            result = email_service.send(
                to=[user.email], subject=subject, body=body, is_html=is_html,
            )
            users_notified += 1
            if result.get("success"):
                emails_sent += 1
            else:
                emails_failed += 1
                logger.warning(
                    "daily-digest: send returned non-success for %s: %s",
                    user.email, result,
                )
        except Exception as e:  # noqa: BLE001 — one bad email mustn't stop the rest
            emails_failed += 1
            logger.error(
                "daily-digest: send raised for %s: %s", user.email, e,
            )

    logger.info(
        "daily-digest: notified %d users (sent=%d, failed=%d, items=%d)",
        users_notified, emails_sent, emails_failed, items_aggregated,
    )
    return DigestSummary(
        ran_at=ran_at,
        users_notified=users_notified,
        emails_sent=emails_sent,
        emails_failed=emails_failed,
        items_aggregated=items_aggregated,
    )
