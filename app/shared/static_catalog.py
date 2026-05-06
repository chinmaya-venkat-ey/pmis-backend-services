"""DB-first-with-fallback membership helper for static catalogs (doc 37 part 1).

Used by validators that historically checked membership against an
in-code tuple (``PROJECT_CATEGORY_CHOICES``, ``ACTIVITY_TYPES``, etc.).
After doc 37 those tuples become **fallbacks** — the active set lives
in the corresponding master table (``project_categories``,
``activity_types``, ``milestone_statuses``, ``activity_statuses``).

The contract:

- When a session is provided AND the catalog has at least one active
  row, the active set comes from the DB.
- Otherwise (no session, or empty catalog) the in-code fallback tuple
  is used. Covers test fixtures on fresh in-memory DBs where init_db
  hasn't run.

Same idiom as ``assert_transition_allowed`` in
``app/api/v3/projects/services/transitions.py`` (which has done this
since doc 20 for the project_status_transitions catalog).
"""
from __future__ import annotations

from typing import Iterable, Optional, Set, Type

from sqlalchemy.orm import Session


def active_codes(
    db: Optional[Session],
    *,
    model: Type,
    fallback: Iterable[str],
) -> Set[str]:
    """Return the set of active codes for a static catalog.

    ``model`` must expose ``code`` (string column) and ``active``
    (boolean column). Both are guaranteed by the doc-37-part-1 master
    table shape.
    """
    if db is not None:
        rows = (
            db.query(model.code)
            .filter(model.active.is_(True))
            .all()
        )
        if rows:
            return {r.code for r in rows}
    return set(fallback)


def is_known_code(
    db: Optional[Session],
    code: str,
    *,
    model: Type,
    fallback: Iterable[str],
) -> bool:
    """Membership check: is ``code`` an active row in the DB catalog,
    or (when the catalog is empty / no session) in the in-code fallback?
    """
    if not code:
        return False
    return code in active_codes(db, model=model, fallback=fallback)
