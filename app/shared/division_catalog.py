"""Active-divisions catalog lookup against the shared ``divisions`` table.

Doc 49: user-mgmt validates ``User.division`` against the same master
table the monolith owns. Both services connect to the same ``pmis_db``
database; user-mgmt declares a read-only ORM mirror of the table at
``app/infrastructure/db/models/division.py`` so the column types are
explicit and the table is created in in-memory test DBs by
``Base.metadata.create_all``.

``is_known_active_division`` lowercases + strips its input, then runs:

    SELECT 1 FROM divisions WHERE code = :code AND active = TRUE

Returns True only when an *active* row matches. Soft-disabled rows
(``active=false``) are treated as unknown — matches the FE picker which
hides them.
"""
from sqlalchemy.orm import Session

from ..infrastructure.db.models.division import DivisionModel


def is_known_active_division(db: Session, code: str) -> bool:
    """True iff ``code`` matches an active row in the ``divisions`` table."""
    if not code:
        return False
    row = (
        db.query(DivisionModel.id)
        .filter(DivisionModel.code == code.strip().lower())
        .filter(DivisionModel.active.is_(True))
        .first()
    )
    return row is not None
