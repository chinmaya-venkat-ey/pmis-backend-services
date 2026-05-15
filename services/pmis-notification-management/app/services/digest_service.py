"""Daily deadline-digest cron logic.

Scans the shared DB for milestones / activities whose end_date is within
`DEADLINE_WINDOW_DAYS` (default 5) OR past due. Resolves recipients
(org_admin of project's owning vendor(s), project_admin / project_member
of the project) cross-schema via DigestRepository, groups items per user,
renders the per-user HTML block, and dispatches one email per user.

Recipient tiers:
  - org_admin      → scope `organization_id` = a vendor mapped to the project
  - project_admin  → scope `project_id` = the project
  - project_member → scope `project_id` = the project

Items skipped when:
  - parent project is closed (status='closed') or soft-deleted
  - milestone / activity itself soft-deleted
  - milestone / activity status='completed'
  - recipient user soft-deleted or non-active
  - recipient user has no email

Ported from
  C:\\Programming\\PMIS\\PMIS-notification-service\\app\\services\\digest_service.py:1-431
with these changes:
  - Cross-schema reads via DigestRepository (queries moved out per PLAN.md §1.2).
  - SQLAlchemy 2.0 `select()` API in the repository.
  - Template lookups via TemplateService (was module-level `render_email`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.repositories.digest_repository import DigestRepository
from app.services.email_service import EmailService
from app.services.template_service import TemplateService
from app.utilities.logger import get_logger


logger = get_logger(__name__)


_TEMPLATE_KIND = "project_deadline_digest"


@dataclass(frozen=True)
class DigestItem:
    """One row to render in a user's email — a single milestone or activity
    nearing or past its end date."""

    project_id: str
    project_name: str
    project_code: str
    level: str          # "Milestone" or "Activity"
    item_id: str
    item_name: str
    end_date: date
    days_remaining: int  # positive = future, negative = overdue, 0 = today


@dataclass(frozen=True)
class DigestSummary:
    """Return value of DigestService.run() — surfaced to the cron caller."""

    ran_at: datetime
    users_notified: int
    emails_sent: int
    emails_failed: int
    items_aggregated: int


def _as_date(d) -> Optional[date]:
    """Coerce a datetime / date / None to a date."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return None


def _fmt_date(d: date) -> str:
    return d.strftime("%d %b %Y")


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


def _render_items_html(items: Iterable[DigestItem]) -> str:
    """Build the per-project HTML block injected as `{items_html}`."""
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
        lines: List[str] = [
            f'<p style="margin-top:12px; margin-bottom:4px;">'
            f"<b>{project_name}</b> ({project_code})</p>",
            '<ul style="margin:0 0 0 20px; padding:0;">',
        ]
        rows = sorted(by_project[pid], key=lambda x: x.days_remaining)
        for it in rows:
            lines.append(_render_item_line(it))
        lines.append("</ul>")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


class DigestService:
    """Orchestrator for the daily-digest cron."""

    def __init__(self, db: Session, email_service: EmailService):
        self.db = db
        self.email_service = email_service
        self.repo = DigestRepository(db)
        self.template_service = TemplateService(db)

    def _aggregate_by_user(
        self, today: date, window_days: int
    ) -> Dict[str, List[DigestItem]]:
        """Build {user_id: [DigestItem, ...]} covering every milestone /
        activity due in the window. De-duped per user."""
        by_user: Dict[str, List[DigestItem]] = {}
        seen_per_user: Dict[str, set] = {}
        recipients_cache: Dict[str, List[str]] = {}

        def _recipients(project_id: str) -> List[str]:
            if project_id not in recipients_cache:
                recipients_cache[project_id] = self.repo.responsible_user_ids(project_id)
            return recipients_cache[project_id]

        def _add(uid: str, item: DigestItem):
            key = (item.level, item.item_id)
            seen = seen_per_user.setdefault(uid, set())
            if key in seen:
                return
            seen.add(key)
            by_user.setdefault(uid, []).append(item)

        for project, milestone in self.repo.find_due_milestones(today, window_days):
            end_date = _as_date(milestone.end_date)
            if end_date is None:
                continue
            days_remaining = (end_date - today).days
            item = DigestItem(
                project_id=project.id,
                project_name=project.name,
                project_code=project.project_code or "",
                level="Milestone",
                item_id=milestone.id,
                item_name=milestone.name,
                end_date=end_date,
                days_remaining=days_remaining,
            )
            for uid in _recipients(project.id):
                _add(uid, item)

        for project, activity in self.repo.find_due_activities(today, window_days):
            end_date = _as_date(activity.end_date)
            if end_date is None:
                continue
            days_remaining = (end_date - today).days
            item = DigestItem(
                project_id=project.id,
                project_name=project.name,
                project_code=project.project_code or "",
                level="Activity",
                item_id=activity.id,
                item_name=activity.name,
                end_date=end_date,
                days_remaining=days_remaining,
            )
            for uid in _recipients(project.id):
                _add(uid, item)

        return by_user

    def run(
        self,
        *,
        today: Optional[date] = None,
        window_days: Optional[int] = None,
    ) -> DigestSummary:
        """Top-level entry point — scan, group, render, send."""
        ran_at = datetime.now(timezone.utc)
        eff_today = today or ran_at.date()
        eff_window = (
            window_days if window_days is not None else int(settings.deadline_window_days)
        )

        by_user = self._aggregate_by_user(eff_today, eff_window)
        items_aggregated = sum(len(items) for items in by_user.values())

        if not by_user:
            logger.info("daily-digest: nothing to send (no qualifying items).")
            return DigestSummary(
                ran_at=ran_at,
                users_notified=0,
                emails_sent=0,
                emails_failed=0,
                items_aggregated=0,
            )

        users = self.repo.get_users_by_ids(list(by_user.keys()))
        by_id = {u.id: u for u in users}

        emails_sent = 0
        emails_failed = 0
        users_notified = 0
        portal_url = (settings.frontend_base_url or "").rstrip("/")

        for user_id, items in by_user.items():
            user = by_id.get(user_id)
            if user is None or not user.email:
                continue
            payload = {
                "first_name": (user.first_name or user.login or "there"),
                "items_html": _render_items_html(items),
                "portal_url": portal_url,
            }
            try:
                subject, body, is_html = self.template_service.render_email(
                    _TEMPLATE_KIND, payload
                )
                result = self.email_service.send(
                    to=[user.email],
                    subject=subject,
                    body=body,
                    is_html=is_html,
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
            except Exception as exc:  # one bad email mustn't stop the rest
                emails_failed += 1
                logger.error("daily-digest: send raised for %s: %s", user.email, exc)

        logger.info(
            "daily-digest: notified=%d sent=%d failed=%d items=%d",
            users_notified, emails_sent, emails_failed, items_aggregated,
        )
        return DigestSummary(
            ran_at=ran_at,
            users_notified=users_notified,
            emails_sent=emails_sent,
            emails_failed=emails_failed,
            items_aggregated=items_aggregated,
        )
