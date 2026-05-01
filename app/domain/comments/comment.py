"""Comment domain entity."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Comment:
    id: str
    target_kind: str       # one of TARGET_KINDS
    target_id: str         # UUID of the target (M/A/T/S id)
    body: str
    author_user_id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[int] = None

    # Embedded author info (filled by repo when joined). Not always present.
    author_login: Optional[str] = None
    author_first_name: Optional[str] = None
    author_last_name: Optional[str] = None
    author_email: Optional[str] = None

    # Attachments belonging to this comment. Populated by the repo on
    # explicit calls; left empty otherwise to keep reads cheap.
    attachments: List["Attachment"] = field(default_factory=list)  # noqa: F821

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "body": self.body,
            "author": {
                "id": self.author_user_id,
                "login": self.author_login,
                "first_name": self.author_first_name,
                "last_name": self.author_last_name,
                "email": self.author_email,
            },
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "attachments": [a.to_dict() for a in (self.attachments or [])],
        }

    def is_deleted(self) -> bool:
        return self.deleted_at is not None
