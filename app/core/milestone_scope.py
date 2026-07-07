"""Vendor-scoped milestone visibility — one shared rule, reused everywhere a
milestone can surface, so the scoping can't drift between endpoints.

Rule: an organization (vendor) assigned to a project only sees MILESTONES where
it has a live ACTIVITY assigned to it (``activity.vendor_id``). Concretely:

  * admin / super_admin  → see ALL milestones (no restriction).
  * a vendor-tied user   → only milestones that have a live activity whose
                           ``vendor_id`` matches the caller's vendor.
  * a non-admin user with NO vendor → sees NOTHING (fail-closed): there is no
                           legitimate no-vendor non-admin user today, and a
                           blanket view would be a leak.

Caller inputs come from the request: ``request.state.user_vendor_id`` and the
``projects:admin_override`` capability (via ``get_caller_is_admin``).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import false, select
from sqlalchemy.sql.elements import ColumnElement

from app.models.activity import Activity
from app.models.milestone import Milestone


def vendor_milestone_filter(
    project_id: str, *, caller_vendor_id: Optional[str], caller_is_admin: bool,
) -> Optional[ColumnElement]:
    """A SQLAlchemy clause restricting ``Milestone`` rows to those the caller may
    see, or ``None`` (no restriction) for admins. Add it to any milestone query::

        clause = vendor_milestone_filter(pid, caller_vendor_id=v, caller_is_admin=a)
        if clause is not None:
            stmt = stmt.where(clause)
    """
    if caller_is_admin:
        return None
    if not caller_vendor_id:
        return false()  # fail-closed: no-vendor non-admin sees nothing
    return Milestone.id.in_(
        select(Activity.milestone_id).where(
            Activity.project_id == project_id,
            Activity.vendor_id == caller_vendor_id,
            Activity.deleted_at.is_(None),
        )
    )


def can_see_milestone(
    db, milestone: Milestone, *, caller_vendor_id: Optional[str], caller_is_admin: bool,
) -> bool:
    """True if the caller may see this specific milestone (for detail endpoints).
    Admins always may; a vendor user may iff their org has a live activity on it;
    a no-vendor non-admin never may."""
    if caller_is_admin:
        return True
    if not caller_vendor_id:
        return False
    if milestone is None:
        return False
    exists = db.execute(
        select(Activity.id)
        .where(Activity.milestone_id == milestone.id)
        .where(Activity.vendor_id == caller_vendor_id)
        .where(Activity.deleted_at.is_(None))
        .limit(1)
    ).first()
    return exists is not None
