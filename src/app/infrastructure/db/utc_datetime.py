"""UtcDateTime — a SQLAlchemy column type that always stores naive UTC.

Doc 27 (date-equality bug fix): incoming datetimes from the FE may carry
a timezone offset (e.g. ``+05:30`` for IST date pickers). The default
``Column(DateTime)`` type maps to ``TIMESTAMP WITHOUT TIME ZONE`` on
Postgres / a plain string on SQLite — neither preserves the offset.
The driver silently writes the wall-clock value, so an IST midnight
becomes a naive ``2026-05-10 00:00:00``. On read it comes back as a
naive datetime that downstream comparison code (``app/shared/date_rules.py``)
incorrectly treats as UTC. The result: a milestone with the same
calendar date as its project gets rejected because, after asymmetric
normalization (project naive-treated-as-UTC vs milestone tz-aware
converted-to-UTC), the milestone start lands 5h30m before the project
start.

The fix: convert every datetime to naive UTC at the storage boundary,
*before* the driver sees it. This guarantees:

  * Storage layer always holds canonical naive UTC.
  * Reads return naive UTC, which the existing comparison helpers
    correctly assume to be UTC.
  * Same-calendar-date inputs from the FE compare equal regardless of
    whether they carried a tz offset or not.

Naive inputs are passed through unchanged on the assumption that the
caller meant UTC (matches ``app/shared/datetime.ensure_aware_utc``
semantics). FE flows that send naive datetimes are accepting that
assumption.

Use this for every persisted datetime column. It is a drop-in
replacement for ``DateTime``: same Python type returned, same
``default=`` / ``onupdate=`` / ``nullable=`` semantics.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.types import DateTime, TypeDecorator


class UtcDateTime(TypeDecorator):
    """Drop-in replacement for ``DateTime`` that normalizes writes to naive UTC.

    On the bind path (Python → DB):
      - ``None``                 → ``None``
      - tz-aware datetime        → converted to UTC, tz stripped
      - naive datetime           → passed through (assumed already UTC)

    On the result path (DB → Python):
      - Whatever the driver returns (typically a naive datetime).

    ``cache_ok = True`` so SQLAlchemy can cache compiled statements
    using this type — no per-instance state.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: Optional[datetime], dialect,
    ) -> Optional[datetime]:
        if value is None:
            return None
        if not isinstance(value, datetime):
            # Defensive: SQLAlchemy passes non-datetime values through some
            # codepaths (e.g. SQL functions). Leave them untouched.
            return value
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(
        self, value: Optional[datetime], dialect,
    ) -> Optional[datetime]:
        # Drivers return naive datetimes for TIMESTAMP WITHOUT TIME ZONE
        # (Postgres) or for SQLite's stored-string DateTime. Returning
        # as-is keeps the existing assume-naive-is-UTC semantics
        # consistent with ``app/shared/datetime.ensure_aware_utc``.
        return value
