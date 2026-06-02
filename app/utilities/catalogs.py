"""Master-data catalog helpers — status / priority / division / category
choice validation.

Mirrors the monolith's pattern (see ``app/shared/static_catalog.py`` and
the per-service ``is_known_code`` helpers): query the cross-schema
``masters.*`` mirror for an ACTIVE row; fall back to a hard-coded tuple
when the catalog is empty (fresh DB before masters-svc bootstrap).

Lookup helpers return ``True`` / ``False``; the caller is responsible
for raising the canonical ``ValidationError`` so error messages stay in
the service layer (matches monolith convention).
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import (
    ActivityStatus as _ActivityStatus,
    Division as _Division,
    MilestoneStatus as _MilestoneStatus,
    Priority as _Priority,
    ProjectCategory as _ProjectCategory,
    ResourceType as _ResourceType,
)


# ---------------------------------------------------------------------------
# Fallback choice tuples (matches monolith ``app/shared/static_catalog.py``).
# Used when the corresponding ``masters.*`` table has zero active rows.
# ---------------------------------------------------------------------------

PROJECT_STATUS_CHOICES: Tuple[str, ...] = ("new", "draft", "published", "closed")
PROJECT_STATUS_DEFAULT: str = "new"

MILESTONE_STATUS_CHOICES: Tuple[str, ...] = ("not_completed", "completed")
MILESTONE_STATUS_DEFAULT: str = "not_completed"

ACTIVITY_STATUS_CHOICES: Tuple[str, ...] = ("not_completed", "completed")
ACTIVITY_STATUS_DEFAULT: str = "not_completed"

PRIORITY_CHOICES: Tuple[str, ...] = ("P1", "P2", "P3")

PROJECT_CATEGORY_CHOICES: Tuple[str, ...] = ("MSAP", "MSIP", "BSP", "others")

OWNER_DIVISION_CHOICES: Tuple[str, ...] = ("tmd1", "tmd2", "others")
"""Built-in division codes seeded by masters-svc. Admin-added division
codes are also accepted via the ``masters.divisions`` catalog lookup."""


# Status terminal-states. ``completed`` is the canonical "done" code for
# milestones / activities (and by extension, tasks / subtasks which mirror
# the same vocabulary). Catalog rows that flip ``is_terminal=true`` are
# treated equivalently.
_TERMINAL_STATUS_CODES: frozenset[str] = frozenset({"completed"})


def is_terminal_status(code: Optional[str]) -> bool:
    """True when ``code`` represents a "completed" terminal state."""
    return (code or "").lower() in _TERMINAL_STATUS_CODES


# ---------------------------------------------------------------------------
# Catalog lookups
# ---------------------------------------------------------------------------

def _has_active_row(db: Session, model) -> bool:
    """Defensive: ``True`` iff the catalog table has at least one active row."""
    stmt = select(model.code).where(model.active.is_(True)).limit(1)
    return db.execute(stmt).first() is not None


def _is_known_code(
    db: Session, model, code: str, fallback: Iterable[str],
) -> bool:
    """Validate ``code`` against the live ``masters.*`` table; fall back
    to the in-code tuple when the table is empty.

    Matches the monolith's ``is_known_code`` two-tier behaviour.
    """
    if code is None:
        return False
    cleaned = str(code).strip()
    if not cleaned:
        return False
    if _has_active_row(db, model):
        return db.execute(
            select(model.code)
            .where(model.code == cleaned)
            .where(model.active.is_(True))
            .limit(1)
        ).first() is not None
    return cleaned in {c.strip() for c in fallback}


# ----- per-domain wrappers (semantic alias so service code reads cleanly)

def is_known_project_status(db: Session, code: str) -> bool:
    """``code`` exists as an active ``project_status_transitions.to_status``
    or is one of the hard-coded fallback statuses. The transition catalog
    is the source of truth on whether a code is "known"; we don't insist
    it appear in a dedicated ``project_statuses`` table because the
    transitions table already captures every valid status implicitly."""
    if code is None:
        return False
    cleaned = str(code).strip()
    if not cleaned:
        return False
    # Lookup via the transitions mirror so we don't need an extra table.
    from app.models._cross_schema import ProjectStatusTransition
    stmt = (
        select(ProjectStatusTransition.to_status)
        .where(ProjectStatusTransition.to_status == cleaned)
        .where(ProjectStatusTransition.active.is_(True))
        .limit(1)
    )
    if db.execute(stmt).first() is not None:
        return True
    return cleaned in PROJECT_STATUS_CHOICES


def is_known_milestone_status(db: Session, code: str) -> bool:
    return _is_known_code(db, _MilestoneStatus, code, MILESTONE_STATUS_CHOICES)


def is_known_activity_status(db: Session, code: str) -> bool:
    return _is_known_code(db, _ActivityStatus, code, ACTIVITY_STATUS_CHOICES)


def is_known_priority(db: Session, code: str) -> bool:
    return _is_known_code(db, _Priority, code, PRIORITY_CHOICES)


def is_known_project_category(db: Session, code: str) -> bool:
    return _is_known_code(db, _ProjectCategory, code, PROJECT_CATEGORY_CHOICES)


def is_known_owner_division(db: Session, code: str) -> bool:
    return _is_known_code(db, _Division, code, OWNER_DIVISION_CHOICES)


def is_known_resource_type(db: Session, resource_type_id: str) -> bool:
    """``resource_type_id`` (UUID) corresponds to an active row in
    ``masters.resource_types``. Returns False for unknown / inactive."""
    if not resource_type_id:
        return False
    return db.execute(
        select(_ResourceType.id)
        .where(_ResourceType.id == resource_type_id)
        .where(_ResourceType.active.is_(True))
        .limit(1)
    ).first() is not None


def active_choices_for(
    db: Session, model, fallback: Iterable[str],
) -> Tuple[str, ...]:
    """Snapshot of currently-active codes for an error-message render."""
    if _has_active_row(db, model):
        rows = db.execute(
            select(model.code).where(model.active.is_(True)).order_by(model.code.asc())
        ).all()
        return tuple(r[0] for r in rows)
    return tuple(fallback)


def active_project_statuses(db: Session) -> Tuple[str, ...]:
    """Renderable list of acceptable project statuses."""
    from app.models._cross_schema import ProjectStatusTransition
    rows = db.execute(
        select(ProjectStatusTransition.to_status)
        .where(ProjectStatusTransition.active.is_(True))
        .distinct()
    ).all()
    if rows:
        return tuple(sorted({r[0] for r in rows}))
    return PROJECT_STATUS_CHOICES


def active_milestone_statuses(db: Session) -> Tuple[str, ...]:
    return active_choices_for(db, _MilestoneStatus, MILESTONE_STATUS_CHOICES)


def active_activity_statuses(db: Session) -> Tuple[str, ...]:
    return active_choices_for(db, _ActivityStatus, ACTIVITY_STATUS_CHOICES)


def active_priorities(db: Session) -> Tuple[str, ...]:
    return active_choices_for(db, _Priority, PRIORITY_CHOICES)


def active_project_categories(db: Session) -> Tuple[str, ...]:
    return active_choices_for(db, _ProjectCategory, PROJECT_CATEGORY_CHOICES)


def active_owner_divisions(db: Session) -> Tuple[str, ...]:
    return active_choices_for(db, _Division, OWNER_DIVISION_CHOICES)
