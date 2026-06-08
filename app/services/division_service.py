"""Business logic for the divisions catalog.

Enforces:
  - Code uniqueness on create
  - Built-in rows can't be deleted (CatalogBuiltinImmutableError)
  - "Delete" = deactivate (active=False); "restore" = reactivate (active=True)

Row-level scoping (e.g. "user only sees divisions in their org") would be
applied here as a filter — currently a no-op pending the user-svc port
discussion of Option C scoping semantics.
"""
from __future__ import annotations

import re
from typing import List

from sqlalchemy.orm import Session

from app.core.errors import (
    CatalogEntryConflictError,
    CatalogEntryNotFoundError,
)
from app.models.division import Division
from app.repositories.division_repository import DivisionRepository
from app.schemas.division import DivisionCreateRequest, DivisionUpdateRequest


class DivisionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DivisionRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[Division]:
        # Future scoping hook: filter by caller's permissions.
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_code(self, code: str) -> Division:
        row = self.repo.get_by_code(code)
        if row is None:
            raise CatalogEntryNotFoundError(f"Division code {code!r} not found")
        return row

    def create(self, payload: DivisionCreateRequest) -> Division:
        # Bug #220: name uniqueness (case-insensitive) — reject duplicate label.
        if self.repo.get_by_label(payload.label) is not None:
            raise CatalogEntryConflictError(
                f"Division name {payload.label!r} already exists",
                details={"label": payload.label},
            )
        # Bug #220: the wire code is generated server-side from the label,
        # never taken from the client. Collisions get a numeric suffix.
        code = self._generate_unique_code(payload.label)
        row = self.repo.create(
            code=code,
            label=payload.label,
            is_builtin=False,
            requires_other=payload.requires_other,
            active=payload.active,
            email=str(payload.email),
            phone_number=payload.phone_number,
        )
        self.db.commit()
        return row

    def update(self, code: str, payload: DivisionUpdateRequest) -> Division:
        row = self.get_by_code(code)
        updates = payload.model_dump(exclude_unset=True)
        if "email" in updates and updates["email"] is not None:
            updates["email"] = str(updates["email"])
        # Bug #220: keep name uniqueness on rename (the wire code is immutable,
        # so a label change must not collide with another division's label).
        new_label = updates.get("label")
        if new_label is not None:
            clash = self.repo.get_by_label(new_label)
            if clash is not None and clash.id != row.id:
                raise CatalogEntryConflictError(
                    f"Division name {new_label!r} already exists",
                    details={"label": new_label},
                )
        self.repo.update(row, **updates)
        self.db.commit()
        return row

    # ------------------------------------------------------------------ helpers
    def _generate_unique_code(self, label: str) -> str:
        """Derive a unique lowercase wire code from the display label
        (Bug #220). Matches the ``^[a-z0-9_-]+$`` column contract; on
        collision appends ``-2``, ``-3`` … until free."""
        base = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")[:64]
        if not base:
            base = "division"
        candidate = base
        suffix = 2
        while self.repo.get_by_code(candidate) is not None:
            tail = f"-{suffix}"
            candidate = f"{base[: 64 - len(tail)]}{tail}"
            suffix += 1
        return candidate

    def delete(self, code: str) -> Division:
        row = self.get_by_code(code)
        # is_builtin is informational only — divisions are fully deletable.
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, code: str) -> Division:
        row = self.get_by_code(code)
        self.repo.reactivate(row)
        self.db.commit()
        return row
