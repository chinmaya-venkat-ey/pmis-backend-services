"""
Role domain model.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from ...shared.datetime import iso_ist


@dataclass
class Role:
    """
    Role domain entity.

    Permissions are sourced from the ``role_permissions`` join table on
    read (doc 21 part B). The legacy in-row JSON column is gone.
    """

    id: int
    name: str
    permissions: List[str]
    builtin: bool
    created_at: datetime
    updated_at: datetime
    description: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permissions": self.permissions,
            "builtin": self.builtin,
            "created_at": iso_ist(self.created_at),
            "updated_at": iso_ist(self.updated_at),
        }
