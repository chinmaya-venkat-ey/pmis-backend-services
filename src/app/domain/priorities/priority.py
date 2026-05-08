"""Priority domain entity (doc 41)."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ...shared.datetime import iso_ist


# In-code fallback used when the DB catalog is empty (test fixtures
# on fresh in-memory DBs that don't run init_db / migrations).
PRIORITY_CHOICES = ("p1", "p2", "p3")
PRIORITY_DEFAULT = "p3"


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
