"""HTTP client for the dashboard's meetings block, sourced from the Java
PMIS-meeting-mom-governance service (read-only).

That service exposes no count/aggregation endpoints and no organisation
dimension, so we pull ONE bounded meetings list and count client-side —
globally, or filtered to an organisation's project-id set. The caller's
bearer token is forwarded (the service requires the Authorization header).

Degrades to ``available: false`` when no URL is configured or on any error.

Buckets derived from ``meetingDate`` (date-only) + ``status``:
  today     = meetingDate == today (IST)
  thisWeek  = meetingDate within the current Mon–Sun week
  upcoming  = meetingDate >= today AND status == SCHEDULED
  completed = status == COMPLETED
``pendingMom`` is not derivable from the meetings list (MoM status lives on
a separate 1:1 record with no bulk/project query), so it is 0 — a
documented gap, not a failure.
"""
from __future__ import annotations

from datetime import date as _date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger
from app.utilities.timezones import IST

logger = get_logger(__name__)


def _unavailable() -> Dict[str, Any]:
    return {
        "available": False, "total": 0, "today": 0,
        "thisWeek": 0, "upcoming": 0, "pendingMom": 0, "completed": 0,
    }


def _parse_date(s: Any) -> Optional[_date]:
    if not s:
        return None
    try:
        return _date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


class MeetingClient:
    def __init__(self) -> None:
        self.base_url = (getattr(settings, "meeting_service_url", None) or "").rstrip("/")
        self.timeout = float(getattr(settings, "meeting_service_timeout_seconds", 6.0))
        self.cap = int(getattr(settings, "meeting_service_list_cap", 2000))
        self.enabled = bool(self.base_url)

    # The deployed meeting service has diverged from the repo source: the
    # current repo lists at ``/meetings`` (context-path + /meetings), while
    # the live deployment lists at ``/getAll``. Both return the same
    # PageResponse ({content, totalElements, ...}) with the same meeting
    # fields, so we try both suffixes and use whichever answers — the
    # dashboard then works against either deployed version.
    _LIST_SUFFIXES = ("/meetings", "/getAll")

    def _fetch_list(self, bearer: Optional[str]) -> Optional[List[Dict[str, Any]]]:
        headers = {"Accept": "application/json"}
        if bearer:
            headers["Authorization"] = bearer
        params = {"size": self.cap, "page": 0}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                for suffix in self._LIST_SUFFIXES:
                    resp = client.get(f"{self.base_url}{suffix}", params=params, headers=headers)
                    if resp.status_code == 404:
                        continue  # try the other path convention
                    if resp.status_code >= 400:
                        logger.warning("Meeting list non-2xx: %s %s", resp.status_code, resp.text[:200])
                        return None
                    body = resp.json()
                    return body.get("content") or body.get("meetings") or []
        except httpx.HTTPError as exc:
            logger.warning("Meeting list fetch failed: %s", exc)
            return None
        logger.warning("Meeting list: no known list path answered (tried %s)", self._LIST_SUFFIXES)
        return None

    def summary(
        self, *, bearer: Optional[str] = None, project_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return _unavailable()
        meetings = self._fetch_list(bearer)
        if meetings is None:
            return _unavailable()

        if project_ids is not None:
            wanted = set(project_ids)
            meetings = [m for m in meetings if (m.get("projectId") in wanted)]

        today = datetime.now(timezone.utc).astimezone(IST).date()
        week_start = today - timedelta(days=today.weekday())   # Monday
        week_end = week_start + timedelta(days=6)              # Sunday

        total = len(meetings)
        today_n = 0
        this_week = 0
        upcoming = 0
        completed = 0
        for m in meetings:
            status = (m.get("status") or "").upper()
            md = _parse_date(m.get("meetingDate"))
            if status == "COMPLETED":
                completed += 1
            if md is None:
                continue
            if md == today:
                today_n += 1
            if week_start <= md <= week_end:
                this_week += 1
            if md >= today and status == "SCHEDULED":
                upcoming += 1

        return {
            "available": True,
            "total": total,
            "today": today_n,
            "thisWeek": this_week,
            "upcoming": upcoming,
            "pendingMom": 0,   # gap: MoM status not queryable in bulk
            "completed": completed,
        }
