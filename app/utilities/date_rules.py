"""Date-validation rules for milestones, activities, tasks, subtasks
(top-level and nested), and their resource sub-entities.

Ported verbatim from the monolith's ``app/shared/date_rules.py`` so the
error messages, calendar-date semantics, and parent-floor / actual-date
ordering rules match the FE's existing expectations byte-for-byte.

Product rules (fixed):
    1. ``entity.start_date >= parent.start_date``           — parent-chain floor
    2. ``entity.end_date >= entity.start_date``             — sanity, no upper cap
    3. ``actual_start_date >= project.start_date``          — project floor (if provided)
    4. ``actual_end_date >= actual_start_date`` OR
       ``actual_end_date >= project.start_date``            — order / project floor

Notes:
    * No upper-bound check against parent.end_date or project.end_date —
      real projects overrun, and end dates may slip arbitrarily. So an
      activity is allowed to end after its milestone ends, etc.
    * Equality is allowed throughout (``>=``), so an activity can start
      the same day its milestone starts.
    * Messages are user-facing: plain English, capitalized, no field
      paths. Match the monolith's strings exactly.
    * Calendar-date semantics (doc-29): rules compare IST calendar dates,
      not UTC instants. The internal ``_normalize`` collapses any
      submitted datetime to IST midnight of its IST-local date so any of
      ``2026-05-04T00:00:00+05:30`` / ``2026-05-04T00:00:00Z`` /
      ``2026-05-04T23:59:59+05:30`` compare equal.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Union

from app.core.errors import ValidationError


IST = timezone(timedelta(hours=5, minutes=30))


def _to_ist_calendar_midnight(dt: Optional[datetime]) -> Optional[datetime]:
    """Collapse ``dt`` to IST midnight of its IST-local calendar date.

    ``None`` passes through. Naive datetimes are treated as UTC (matches
    the monolith convention).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ist_dt = dt.astimezone(IST)
    return datetime(ist_dt.year, ist_dt.month, ist_dt.day, tzinfo=IST)


def to_ist_calendar_date(
    value: Union[str, date, datetime, None],
) -> Optional[date]:
    """Normalise any calendar-date input to the IST-local calendar ``date``.

    Guards a pure-``date`` field (e.g. an allocation's planned deployment
    date) against clients that serialise the picked day as a full instant.
    A local IST midnight sent as a UTC ``Z`` timestamp lands on the previous
    UTC day; taking its IST-local date recovers the day the user picked so
    the stored/returned value never shifts by a timezone.

    Accepts:
      * ``None``                 → ``None``
      * ``date`` (not datetime)  → returned unchanged
      * ``datetime``             → its IST-local calendar date
      * ``str`` plain ``YYYY-MM-DD``            → that date, verbatim
      * ``str`` ISO datetime (``T`` present, optional ``Z``/offset)
                                 → its IST-local calendar date

    A plain date (what the FE sends today) is therefore untouched; only a
    datetime-shaped value is projected onto the IST calendar. Anything
    unparseable is returned as-is so Pydantic raises its own clear error.
    """
    if value is None or value == "":
        return None
    # NB: ``datetime`` is a subclass of ``date`` — check it first.
    if isinstance(value, datetime):
        return _to_ist_calendar_midnight(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if "T" not in s and " " not in s:
            # Plain calendar date — keep exactly what was sent.
            try:
                return date.fromisoformat(s)
            except ValueError:
                return value
        try:
            # ``fromisoformat`` only learned ``Z`` in 3.11; normalise it.
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return value
        return _to_ist_calendar_midnight(dt).date()
    return value


def _normalize(v: Optional[datetime]) -> Optional[datetime]:
    return _to_ist_calendar_midnight(v)


def _fmt(d: Optional[datetime]) -> str:
    """Format ``d`` as ``YYYY-MM-DD`` for end-user error messages.

    ``d`` is expected to be the output of ``_normalize`` (IST midnight,
    tz-aware) so the formatted string is the IST calendar date.
    """
    return d.strftime("%Y-%m-%d") if d else ""


def _entity_check_start_against_parent_floor(
    entity_start_n: Optional[datetime],
    parent_start_n: Optional[datetime],
    entity_cap: str,
    parent_label: str,
) -> None:
    if (
        parent_start_n is not None and entity_start_n is not None
        and entity_start_n < parent_start_n
    ):
        raise ValidationError(
            f"{entity_cap} start date cannot be before the {parent_label} "
            f"start date ({_fmt(parent_start_n)})."
        )


def _entity_check_end_after_start(
    entity_start_n: Optional[datetime],
    entity_end_n: Optional[datetime],
    entity_cap: str,
) -> None:
    if (
        entity_start_n is not None and entity_end_n is not None
        and entity_end_n < entity_start_n
    ):
        raise ValidationError(
            f"{entity_cap} end date cannot be before its start date."
        )


def _entity_check_actual_start_against_project_floor(
    actual_start_n: Optional[datetime],
    project_start_n: Optional[datetime],
    entity_cap: str,
) -> None:
    if (
        actual_start_n is not None and project_start_n is not None
        and actual_start_n < project_start_n
    ):
        raise ValidationError(
            f"{entity_cap} actual start date cannot be before the project "
            f"start date ({_fmt(project_start_n)})."
        )


def _entity_check_actual_end_ordering(
    actual_end_n: Optional[datetime],
    actual_start_n: Optional[datetime],
    project_start_n: Optional[datetime],
    entity_cap: str,
) -> None:
    if actual_end_n is None:
        return
    if actual_start_n is not None:
        if actual_end_n < actual_start_n:
            raise ValidationError(
                f"{entity_cap} actual end date cannot be before the "
                f"actual start date."
            )
    elif project_start_n is not None and actual_end_n < project_start_n:
        raise ValidationError(
            f"{entity_cap} actual end date cannot be before the "
            f"project start date ({_fmt(project_start_n)})."
        )


def validate_entity_dates(
    *,
    entity_start: datetime,
    entity_end: datetime,
    actual_start: Optional[datetime],
    actual_end: Optional[datetime],
    parent_start_date: datetime,
    project_start_date: datetime,
    entity_label: str = "entity",
    parent_label: str = "parent",
) -> None:
    """Apply the four date rules. Raises ``ValidationError`` (HTTP 422)
    on the first violation.

    ``entity_label`` / ``parent_label`` populate the user-facing message
    (``Milestone`` / ``project``, ``Activity`` / ``milestone``, etc.).
    Pass them in whatever casing you want to appear.

    Project floor (rule 1) is skipped silently when ``parent_start_date``
    is ``None`` (e.g. a fresh project with no dates set yet); the entity
    can still be created and the floor will be enforced once the parent
    gains a start date via PATCH.

    Checks fire in the documented order — first violation wins, so the
    user-facing message for any input is byte-identical to the legacy
    in-line form.
    """
    entity_start_n = _normalize(entity_start)
    entity_end_n = _normalize(entity_end)
    actual_start_n = _normalize(actual_start)
    actual_end_n = _normalize(actual_end)
    parent_start_n = _normalize(parent_start_date)
    project_start_n = _normalize(project_start_date)

    entity_cap = entity_label.capitalize()

    _entity_check_start_against_parent_floor(
        entity_start_n, parent_start_n, entity_cap, parent_label,
    )
    _entity_check_end_after_start(
        entity_start_n, entity_end_n, entity_cap,
    )
    _entity_check_actual_start_against_project_floor(
        actual_start_n, project_start_n, entity_cap,
    )
    _entity_check_actual_end_ordering(
        actual_end_n, actual_start_n, project_start_n, entity_cap,
    )


def _resource_check_onboard_floor(
    onboard_n: Optional[datetime],
    project_start_n: Optional[datetime],
) -> None:
    if (
        onboard_n is not None and project_start_n is not None
        and onboard_n < project_start_n
    ):
        raise ValidationError(
            f"Onboard date cannot be before the project start date "
            f"({_fmt(project_start_n)})."
        )


def _resource_check_actual_onboard_floor(
    actual_onboard_n: Optional[datetime],
    project_start_n: Optional[datetime],
) -> None:
    if (
        actual_onboard_n is not None and project_start_n is not None
        and actual_onboard_n < project_start_n
    ):
        raise ValidationError(
            f"Actual onboard date cannot be before the project start date "
            f"({_fmt(project_start_n)})."
        )


def _resource_check_offboard_ordering(
    offboard_n: Optional[datetime],
    onboard_n: Optional[datetime],
    project_start_n: Optional[datetime],
) -> None:
    if offboard_n is None:
        return
    if onboard_n is not None:
        if offboard_n < onboard_n:
            raise ValidationError(
                "Offboard date cannot be before the onboard date."
            )
    elif project_start_n is not None and offboard_n < project_start_n:
        raise ValidationError(
            f"Offboard date cannot be before the project start date "
            f"({_fmt(project_start_n)})."
        )


def _resource_check_actual_offboard_ordering(
    actual_offboard_n: Optional[datetime],
    actual_onboard_n: Optional[datetime],
    project_start_n: Optional[datetime],
) -> None:
    if actual_offboard_n is None:
        return
    if actual_onboard_n is not None:
        if actual_offboard_n < actual_onboard_n:
            raise ValidationError(
                "Actual offboard date cannot be before the actual "
                "onboard date."
            )
    elif project_start_n is not None and actual_offboard_n < project_start_n:
        raise ValidationError(
            f"Actual offboard date cannot be before the project "
            f"start date ({_fmt(project_start_n)})."
        )


def validate_resource_dates(
    *,
    onboard: Optional[datetime],
    actual_onboard: Optional[datetime],
    offboard: Optional[datetime],
    actual_offboard: Optional[datetime],
    project_start_date: datetime,
) -> None:
    """Floor + ordering rules for a resource sub-entity. All four input
    dates are optional. Matches the monolith's resource-date rules.

    Checks fire in the documented order — first violation wins, so the
    user-facing message for any input is byte-identical to the legacy
    in-line form.
    """
    onboard_n = _normalize(onboard)
    actual_onboard_n = _normalize(actual_onboard)
    offboard_n = _normalize(offboard)
    actual_offboard_n = _normalize(actual_offboard)
    project_start_n = _normalize(project_start_date)

    _resource_check_onboard_floor(onboard_n, project_start_n)
    _resource_check_actual_onboard_floor(actual_onboard_n, project_start_n)
    _resource_check_offboard_ordering(offboard_n, onboard_n, project_start_n)
    _resource_check_actual_offboard_ordering(
        actual_offboard_n, actual_onboard_n, project_start_n,
    )
