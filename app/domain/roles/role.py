"""Role domain entity — ported verbatim from the monolith."""
from dataclasses import dataclass
from datetime import datetime
from typing import List


@dataclass
class Role:
    id: int
    name: str
    permissions: List[str]
    builtin: bool
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "permissions": self.permissions,
            "builtin": self.builtin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
