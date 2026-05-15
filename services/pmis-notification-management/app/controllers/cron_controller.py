"""CronController — HTTP adapter for /notification/cron/daily-digest.

Unpacks the (optional) cron-driven request body, invokes DigestService,
and shapes the response. Date parsing fails fast with a clear error.
"""
from __future__ import annotations

from datetime import date

from app.core.errors import ValidationError
from app.schemas.digest import DigestRequest, DigestResponse
from app.services.digest_service import DigestService


class CronController:
    def __init__(self, service: DigestService):
        self.service = service

    def run_daily_digest(self, payload: DigestRequest) -> DigestResponse:
        today = self._parse_today(payload.today)
        summary = self.service.run(today=today, window_days=payload.window_days)
        return DigestResponse(
            ran_at=summary.ran_at,
            users_notified=summary.users_notified,
            emails_sent=summary.emails_sent,
            emails_failed=summary.emails_failed,
            items_aggregated=summary.items_aggregated,
        )

    @staticmethod
    def _parse_today(raw: str | None) -> date | None:
        if not raw:
            return None
        try:
            return date.fromisoformat(raw.strip())
        except ValueError as exc:
            raise ValidationError(
                f"Invalid 'today' format {raw!r}; expected ISO date (YYYY-MM-DD)",
                code="DIGEST_TODAY_INVALID",
            ) from exc
