"""Cross-schema reader for users associated with a project via
organization (vendor) membership and/or division membership.

Powers ``POST /associated-users`` and the owner_division / concerned_divisions
sections of ``GET /projects/{uuid}/team-page``.

Sources:
  - ``project.project_vendors``          — the project's organizations
  - ``project.activities.concerned_divisions``
                                         — concerned-division set
  - ``project.projects.owner``           — owner division
  - ``users.users`` (cross-schema)       — for the actual user rows
  - ``masters.vendors`` / ``masters.divisions`` (cross-schema)
                                         — for hydrating names/labels
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models._cross_schema import (
    Division as MirrorDivision,
    User as MirrorUser,
    Vendor as MirrorVendor,
)
from app.models.activity import Activity
from app.models.project import Project
from app.models.project_vendor import ProjectVendor


class AssociatedUsersRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_project_organization_ids(self, project_id: str) -> List[str]:
        """Vendor IDs joined to this project via project_vendors."""
        rows = self.db.execute(
            select(ProjectVendor.vendor_id)
            .where(ProjectVendor.project_id == project_id)
        ).scalars().all()
        return list(rows)

    def get_project_division_codes(
        self, project_id: str,
    ) -> tuple[Optional[str], List[str]]:
        """Return (owner_division, concerned_divisions_union).

        owner_division is ``projects.owner`` (a division code or None).
        concerned_divisions_union is the de-duplicated list of every code
        appearing in ``activities.concerned_divisions`` (JSONB list) across
        the project's live activities.
        """
        owner_division: Optional[str] = self.db.execute(
            select(Project.owner)
            .where(Project.id == project_id)
        ).scalar()

        activity_rows = self.db.execute(
            select(Activity.concerned_divisions)
            .where(Activity.project_id == project_id)
            .where(Activity.deleted_at.is_(None))
        ).all()

        concerned: Set[str] = set()
        for (codes,) in activity_rows:
            if not codes:
                continue
            for c in codes:
                if isinstance(c, str) and c:
                    concerned.add(c)
        return owner_division, sorted(concerned)

    def fetch_users(
        self,
        vendor_ids: List[str],
        division_codes: List[str],
    ) -> List[MirrorUser]:
        """Return live (non-deleted) users matching either filter.

        A user is included if ``users.vendor_id`` is in ``vendor_ids`` OR
        ``users.division`` is in ``division_codes``. Caller is responsible
        for computing per-user provenance from the returned rows.
        """
        if not vendor_ids and not division_codes:
            return []

        conditions = []
        if vendor_ids:
            conditions.append(MirrorUser.vendor_id.in_(vendor_ids))
        if division_codes:
            conditions.append(MirrorUser.division.in_(division_codes))

        stmt = (
            select(MirrorUser)
            .where(MirrorUser.deleted_at.is_(None))
            .where(or_(*conditions) if len(conditions) > 1 else conditions[0])
            .order_by(MirrorUser.login.asc())
        )
        return list(self.db.execute(stmt).scalars())

    # ── masters hydration ────────────────────────────────────────────────────

    def get_division_by_id(self, division_id: int) -> Optional[MirrorDivision]:
        """Single masters.divisions row by integer id, or None."""
        return self.db.execute(
            select(MirrorDivision).where(MirrorDivision.id == division_id)
        ).scalar()

    def get_vendors_by_ids(
        self, vendor_ids: List[str],
    ) -> Dict[str, MirrorVendor]:
        """Map vendor_id → masters.vendors row for the given ids."""
        if not vendor_ids:
            return {}
        rows = self.db.execute(
            select(MirrorVendor).where(MirrorVendor.id.in_(vendor_ids))
        ).scalars()
        return {v.id: v for v in rows}

    def get_divisions_by_codes(
        self, codes: List[str],
    ) -> Dict[str, MirrorDivision]:
        """Map division code → masters.divisions row for the given codes."""
        if not codes:
            return {}
        rows = self.db.execute(
            select(MirrorDivision).where(MirrorDivision.code.in_(codes))
        ).scalars()
        return {d.code: d for d in rows}
