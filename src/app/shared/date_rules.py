"""
Shared date-validation rules for milestones, activities, tasks, subtasks,
and their resource sub-entities.

Product rules (fixed):
    1. entity.start_date >= parent.start_date (parent-chain floor)
    2. entity.end_date >= entity.start_date (sanity; no upper cap)
    3. actual_start_date, if present, >= project.start_date (project floor)
    4. actual_end_date, if present, >= actual_start_date OR project.start_date

Notes:
    * No upper-bound check against parent.end_date or project.end_date --
      real projects overrun, and end dates are allowed to slip arbitrarily.
    * Messages are user-facing: plain English, capitalized, no field paths.
    * Calendar-date semantics (doc 29 / doc 30 follow-up): the rules
      describe IST calendar-date comparisons, not UTC-instant ordering.
      ``_normalize`` collapses any submitted datetime to IST midnight of
      its IST-local calendar date so the comparison is robust to:
        - legacy stored values that pre-date IstCalendarDate normalization
          (e.g. a project created before doc 29 was deployed has its
          ``start_date`` stored as the FE-supplied UTC instant directly)
        - cross-format inputs (UTC-Z vs IST-+05:30 vs naive)
        - end-of-day vs midnight encodings of the same calendar day
      Without this collapse, a legacy project stored as ``YYYY-MM-DD
      00:00 UTC`` (5h30m AHEAD of the doc-29 canonical IST-midnight value
      ``YYYY-MM-(DD-1) 18:30 UTC``) makes a same-IST-day milestone look
      strictly earlier and the floor rule rejects.
"""
from datetime import datetime
from typing import Optional

from ..core.errors import ValidationError
from .datetime import to_ist_calendar_midnight


def _normalize(v: Optional[datetime]) -> Optional[datetime]:
    """
    Normalize a datetime for cross-comparison on IST calendar-date semantics.

    Returns IST midnight of the IST-local calendar date (a tz-aware
    datetime in IST). Two inputs that represent the same IST calendar
    date — regardless of how they were originally encoded — produce the
    same return value, so equality and ordering reflect calendar-day
    semantics.

    None passes through. Non-datetime inputs aren't expected (validators
    upstream coerce to datetime); if one slips in, ``to_ist_calendar_
    midnight`` returns it unchanged so the existing comparison fires the
    same TypeError it did pre-fix.
    """
    if v is None:
        return None
    return to_ist_calendar_midnight(v)


def _fmt(d: Optional[datetime]) -> str:
    """Format date as YYYY-MM-DD for end-user messages.

    ``d`` is expected to be the output of ``_normalize`` (i.e. IST
    midnight, tz-aware). ``strftime`` operates on the wall-clock fields
    of the datetime, so the formatted string is the IST calendar date.
    """
    return d.strftime("%Y-%m-%d") if d else ""


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
    """
    Apply the four date rules. Raises ValidationError on violation.

    entity_label / parent_label are used in messages, e.g. "Milestone" /
    "project". Pass them in whatever casing you want to appear.
    """
    entity_start_n = _normalize(entity_start)
    entity_end_n = _normalize(entity_end)
    actual_start_n = _normalize(actual_start)
    actual_end_n = _normalize(actual_end)
    parent_start_n = _normalize(parent_start_date)
    project_start_n = _normalize(project_start_date)

    entity_cap = entity_label.capitalize()

    if entity_start_n < parent_start_n:
        raise ValidationError(
            f"{entity_cap} start date cannot be before the {parent_label} start date "
            f"({_fmt(parent_start_n)})."
        )
    if entity_end_n < entity_start_n:
        raise ValidationError(
            f"{entity_cap} end date cannot be before its start date."
        )
    if actual_start_n is not None and actual_start_n < project_start_n:
        raise ValidationError(
            f"{entity_cap} actual start date cannot be before the project start date "
            f"({_fmt(project_start_n)})."
        )
    if actual_end_n is not None:
        if actual_start_n is not None:
            if actual_end_n < actual_start_n:
                raise ValidationError(
                    f"{entity_cap} actual end date cannot be before the actual start date."
                )
        else:
            if actual_end_n < project_start_n:
                raise ValidationError(
                    f"{entity_cap} actual end date cannot be before the project start date "
                    f"({_fmt(project_start_n)})."
                )


def validate_resource_dates(
    *,
    onboard: Optional[datetime],
    actual_onboard: Optional[datetime],
    offboard: Optional[datetime],
    actual_offboard: Optional[datetime],
    project_start_date: datetime,
    entity_label: str = "resource",
) -> None:
    """
    Apply floor-and-ordering rules to a resource sub-entity. All four dates
    are optional.
    """
    onboard_n = _normalize(onboard)
    actual_onboard_n = _normalize(actual_onboard)
    offboard_n = _normalize(offboard)
    actual_offboard_n = _normalize(actual_offboard)
    project_start_n = _normalize(project_start_date)

    if onboard_n is not None and onboard_n < project_start_n:
        raise ValidationError(
            f"Onboard date cannot be before the project start date "
            f"({_fmt(project_start_n)})."
        )
    if actual_onboard_n is not None and actual_onboard_n < project_start_n:
        raise ValidationError(
            f"Actual onboard date cannot be before the project start date "
            f"({_fmt(project_start_n)})."
        )
    if offboard_n is not None:
        if onboard_n is not None:
            if offboard_n < onboard_n:
                raise ValidationError(
                    "Offboard date cannot be before the onboard date."
                )
        else:
            if offboard_n < project_start_n:
                raise ValidationError(
                    f"Offboard date cannot be before the project start date "
                    f"({_fmt(project_start_n)})."
                )
    if actual_offboard_n is not None:
        if actual_onboard_n is not None:
            if actual_offboard_n < actual_onboard_n:
                raise ValidationError(
                    "Actual offboard date cannot be before the actual onboard date."
                )
        else:
            if actual_offboard_n < project_start_n:
                raise ValidationError(
                    f"Actual offboard date cannot be before the project start date "
                    f"({_fmt(project_start_n)})."
                )
