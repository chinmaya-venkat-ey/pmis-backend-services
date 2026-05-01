"""Attachment domain entity."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Attachment:
    id: str
    # Either bound to a comment (comment_id NOT NULL, target_kind/id NULL),
    # OR a standalone node attachment (comment_id NULL, target_kind/id NOT NULL).
    comment_id: Optional[str]
    target_kind: Optional[str]
    target_id: Optional[str]
    original_filename: str
    storage_key: str           # relative path under storage base
    mime_type: str
    size_bytes: int
    uploaded_by_user_id: int
    uploaded_at: datetime
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[int] = None

    # Optional embedded uploader info.
    uploader_login: Optional[str] = None
    uploader_first_name: Optional[str] = None
    uploader_last_name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "comment_id": self.comment_id,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "original_filename": self.original_filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "uploaded_by": {
                "id": self.uploaded_by_user_id,
                "login": self.uploader_login,
                "first_name": self.uploader_first_name,
                "last_name": self.uploader_last_name,
            },
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            # storage_key is an internal detail — never returned to clients.
        }

    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def is_standalone(self) -> bool:
        """True when this attachment isn't bound to a comment."""
        return self.comment_id is None
