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
"""
from datetime import datetime, timezone
from typing import Optional

from ..core.errors import ValidationError


def _normalize(v: Optional[datetime]) -> Optional[datetime]:
    """
    Normalize a datetime for cross-comparison.

    SQLite's DateTime column returns naive datetimes; Pydantic parses ISO
    strings with a Z suffix as timezone-aware. We coerce everything to
    naive UTC for consistent ordering.
    """
    if v is None:
        return None
    if v.tzinfo is not None:
        return v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


def _fmt(d: Optional[datetime]) -> str:
    """Format date as YYYY-MM-DD for end-user messages."""
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
