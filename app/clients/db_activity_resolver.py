"""DB-backed activity resolver — a drop-in for ProjectManagementClient that
reads ``project.activities`` from the shared DB instead of calling
project-management over HTTP.

Exposes the same two methods the evaluator + SLA cron use
(``get_activity`` / ``get_activity_project_id``) and returns the same
camelCase dict shape, so callers are unchanged — but no bearer token is
needed. Used by the daily SLA cron so it can run on a shared secret alone.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import Activity


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


class DbActivityResolver:
    def __init__(self, db: Session):
        self.db = db
        self._cache: Dict[str, Optional[Dict[str, Any]]] = {}

    def get_activity(
        self, activity_id: str, bearer_token: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if activity_id in self._cache:
            return self._cache[activity_id]
        # ``deleted_at IS NULL`` — a soft-deleted activity is hidden by
        # project-management (404) and must be invisible here too, else the
        # contract keeps treating it as live and its SLA rows keep surfacing.
        row = self.db.execute(
            select(Activity).where(
                Activity.id == activity_id,
                Activity.deleted_at.is_(None),
            )
        ).scalars().first()
        data = None if row is None else {
            "id": row.id,
            "projectId": row.project_id,
            "milestoneId": row.milestone_id,
            "name": row.name,
            "status": row.status,
            "startDate": _iso(row.start_date),
            "endDate": _iso(row.end_date),
            "actualStartDate": _iso(row.actual_start_date),
            "actualEndDate": _iso(row.actual_end_date),
        }
        self._cache[activity_id] = data
        return data

    def get_activity_project_id(
        self, activity_id: str, bearer_token: Optional[str] = None,
    ) -> Optional[str]:
        activity = self.get_activity(activity_id, bearer_token)
        return activity.get("projectId") if activity else None
