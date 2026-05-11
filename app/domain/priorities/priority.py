"""Priority domain entity (doc 41)."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ...shared.datetime import iso_ist


# In-code fallback used when the DB catalog is empty (test fixtures
# on fresh in-memory DBs that don't run init_db / migrations).
#
# UI-alignment migration: codes are persisted in canonical UPPERCASE
# (``P1`` / ``P2`` / ``P3``) so the FE shows them verbatim without
# a per-render uppercase translation. The Pydantic ``_normalize_priority``
# validators on every M/A/T/S schema uppercase incoming values before
# validation, so legacy callers still sending lowercase ``"p1"`` keep
# working through the transition (input-tolerance).
PRIORITY_CHOICES = ("P1", "P2", "P3")
PRIORITY_DEFAULT = "P3"


@dataclass
class Priority:
    id: str
    code: str
    name: str
    description: Optional[str]
    position: int
    active: bool
    is_builtin: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "position": self.position,
            "active": self.active,
            "is_builtin": self.is_builtin,
            "created_at": iso_ist(self.created_at),
            "updated_at": iso_ist(self.updated_at),
            "deleted_at": iso_ist(self.deleted_at),
        }
