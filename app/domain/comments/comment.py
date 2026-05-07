"""Comment domain entity (doc 35: unified send-event model).

A comment row is one "send event" — like a single email. It carries:
  - a body (optional)
  - an attachments list (optional)
The list contains lightweight info objects, NOT separate domain entities,
because they no longer have their own DB row.

Validation: at least one of (body, attachments) must be non-empty. The
service layer enforces this; the dataclass itself is permissive.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from ...shared.datetime import iso_ist


@dataclass
class AttachmentInfo:
    """One file's metadata, stored inline on a comment row's JSON column.

    No DB id of its own. Identity is the URL — the FE fetches bytes
    directly from this URL (no BE-streaming download path). The senior's
    instruction: "we will save url of the attachment (ip, port and all)
    like wherever it is uploaded" — this is that URL.
    """
    url: str                    # external file server URL
    filename: str               # original filename (display only)
    mime_type: str              # for the FE to set Content-Type on render
    size_bytes: int             # for display + FE-side prefetch budgeting
    uploaded_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "filename": self.filename,
            "mimeType": self.mime_type,
            "sizeBytes": self.size_bytes,
            "uploadedAt": iso_ist(self.uploaded_at),
        }

    @classmethod
    def from_json_entry(cls, entry: dict) -> "AttachmentInfo":
        """Hydrate from the shape we persist in the JSON column.

        Tolerant of legacy keys (snake_case) so a downgrade or a
        partially-migrated row doesn't blow up the read path.
        """
        ua = entry.get("uploadedAt") or entry.get("uploaded_at")
        if isinstance(ua, str):
            try:
                ua = datetime.fromisoformat(ua.replace("Z", "+00:00"))
            except ValueError:
                ua = None
        return cls(
            url=entry.get("url") or "",
            filename=entry.get("filename") or entry.get("original_filename") or "unnamed",
            mime_type=(
                entry.get("mimeType")
                or entry.get("mime_type")
                or "application/octet-stream"
            ),
            size_bytes=int(
                entry.get("sizeBytes") or entry.get("size_bytes") or 0
            ),
            uploaded_at=ua,
        )


@dataclass
class Comment:
    id: str
    target_kind: str       # one of TARGET_KINDS
    target_id: str         # UUID of the target (M/A/T/S id)
    body: Optional[str]    # NULL when the row is attachment-only
    # Doc 26: user-id fields are UUID strings.
    author_user_id: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None

    # Embedded author info (filled by repo when joined). Not always present.
    author_login: Optional[str] = None
    author_first_name: Optional[str] = None
    author_last_name: Optional[str] = None
    author_email: Optional[str] = None

    # Doc 35: attachments are inline metadata objects, not separate domain
    # entities with their own ids. The repo fills this from the JSON column.
    attachments: List[AttachmentInfo] = field(default_factory=list)

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
            "created_at": iso_ist(self.created_at),
            "updated_at": iso_ist(self.updated_at),
            "deleted_at": iso_ist(self.deleted_at),
            "attachments": [a.to_dict() for a in (self.attachments or [])],
        }

    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def is_attachment_only(self) -> bool:
        """True iff the row has no body but at least one attachment."""
        body_empty = (self.body is None) or (str(self.body).strip() == "")
        return body_empty and bool(self.attachments)
