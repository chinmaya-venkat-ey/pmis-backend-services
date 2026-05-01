"""Division repository — backs the project-owner picker.

Reads + admin-curated CRUD. The seed of the three built-in rows
(``tmd1`` / ``tmd2`` / ``others``) lives in ``init_db``; this repo handles
runtime CRUD via the consolidated ``/api/v3/master/divisions`` router (doc
20). The pre-doc-20 auto-insert path that mirrored every project's
``ownerOther`` label into a divisions row was removed — the catalog is now
strictly admin-managed (you'll see the deletion of ``upsert_user_division``
in the doc-20 git diff).
"""
import re
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models.division import DivisionModel


def slugify(label: str) -> str:
    """Lowercase + strip + replace whitespace runs and non-alnum chars
    with a single underscore. Used to mint a wire code from a human label.

        slugify('  Engineering R&D  ') == 'engineering_r_d'

    Two labels that differ only in casing or punctuation collapse to the
    same code (so the next user picking 'Engineering' from the dropdown
    doesn't accidentally create a third row).
    """
    s = (label or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s


class DivisionRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- Reads -----------------------------------------------------------

    def list_active(self) -> List[DivisionModel]:
        """All active divisions in stable display order: built-ins first
        (in code order), then user-added rows in created_at order. Used by
        the FE division/owner pickers."""
        return (
            self.db.query(DivisionModel)
            .filter(DivisionModel.active.is_(True))
            .order_by(
                DivisionModel.is_builtin.desc(),
                DivisionModel.id.asc(),
            )
            .all()
        )

    def list_all(self) -> List[DivisionModel]:
        """Every division row including soft-disabled (active=False) ones.

        Used by the master-data admin views — lets the admin see what was
        previously deactivated and restore it. Same display order as
        ``list_active``.
        """
        return (
            self.db.query(DivisionModel)
            .order_by(
                DivisionModel.is_builtin.desc(),
                DivisionModel.id.asc(),
            )
            .all()
        )

    def get_by_code(self, code: str) -> Optional[DivisionModel]:
        """Lookup by lowercase wire code, ACTIVE rows only. Returns None
        on miss or when the row is currently soft-disabled."""
        if not code:
            return None
        return (
            self.db.query(DivisionModel)
            .filter(DivisionModel.code == code.strip().lower())
            .filter(DivisionModel.active.is_(True))
            .first()
        )

    def get_by_code_any(self, code: str) -> Optional[DivisionModel]:
        """Lookup by code, regardless of active state. Used by the admin
        CRUD endpoints which need to operate on soft-disabled rows."""
        if not code:
            return None
        return (
            self.db.query(DivisionModel)
            .filter(DivisionModel.code == code.strip().lower())
            .first()
        )

    def is_known_code(self, code: str) -> bool:
        return self.get_by_code(code) is not None

    # ---- Writes (doc 20: admin CRUD via /api/v3/master/divisions) --------

    def create(
        self,
        *,
        code: Optional[str],
        label: str,
        requires_other: bool = False,
    ) -> DivisionModel:
        """Insert a new admin-managed (non-built-in) division.

        ``code`` is optional — when omitted the label is slugified to
        derive one. Always lowercased / underscored on the wire. The
        caller is responsible for uniqueness checking via
        ``get_by_code_any`` and for committing the transaction.

        ``is_builtin`` is hard-coded to False here. Built-in rows are only
        created by the ``init_db`` seed and cannot be re-created via the
        API even if their code is reused (the unique constraint stops it).
        """
        wire_code = (code or "").strip().lower() or slugify(label)
        if not wire_code:
            # Defensive — caller's schema should prevent empty labels.
            raise ValueError("division code/label produces an empty wire code")
        row = DivisionModel(
            code=wire_code,
            label=(label or "").strip(),
            is_builtin=False,
            requires_other=requires_other,
            active=True,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def update(
        self,
        code: str,
        *,
        label: Optional[str] = None,
        requires_other: Optional[bool] = None,
    ) -> Optional[DivisionModel]:
        """Patch the label / requires_other on an existing row.

        ``code`` itself is NEVER updatable — it's the wire identifier
        every project's ``owner`` column points at; renaming would break
        every existing reference. The route layer enforces this by
        omitting ``code`` from the patch schema.

        Returns the updated row or None if not found. Caller commits.
        """
        row = self.get_by_code_any(code)
        if row is None:
            return None
        if label is not None:
            row.label = label.strip()
        if requires_other is not None:
            row.requires_other = bool(requires_other)
        self.db.flush()
        return row

    def set_active(self, code: str, active: bool) -> Optional[DivisionModel]:
        """Soft-delete (active=False) or restore (active=True) a row.

        Built-in rows reject deactivation — they back the strict-division
        validator on every project create / user create / activity-resource
        create, so toggling them off would break existing flows. The route
        layer 403s before this point; this method is a defensive no-op
        guard.

        Returns the row, or None if not found.
        """
        row = self.get_by_code_any(code)
        if row is None:
            return None
        if row.is_builtin and not active:
            # Refuse to deactivate a built-in. Caller checks first; this
            # is just belt-and-braces.
            return row
        row.active = bool(active)
        self.db.flush()
        return row
