"""User domain entity — ported verbatim from the monolith.

Kept identical to ``pmis-backend/app/domain/users/user.py`` so response
shapes match across services and the Phase 4 swap is a drop-in change.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    id: int
    login: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    admin: bool
    status: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "login": self.login,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "admin": self.admin,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def full_name(self) -> str:
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        if self.first_name:
            return self.first_name
        if self.last_name:
            return self.last_name
        return self.login

    def is_active(self) -> bool:
        return self.status == "active"
