"""DocumentAccessRule — per-document role-based access control (#323).

A "document" is an attachment row on ``project.comments`` (``body IS NULL``,
files in the JSONB ``attachments`` column). By default a document is PUBLIC —
visible/downloadable by anyone who can read its project. As soon as a
superadmin/admin adds ONE access rule to a document it becomes RESTRICTED
(whitelist): only superadmin/admin, the uploader, and users who match a live
rule may see or download it.

Each rule names a ROLE plus a scope the role must be held at:

  * ``role_name``        the role (e.g. ``division_approver``, ``project_member``).
  * ``project_id``       the document's project — always set; also the default
                         (project-scope) selector when no org/division is given.
  * ``organization_id``  optional vendor scope (org-scoped role holders).
  * ``division``         optional division restriction (division-role holders,
                         combined with ``organization_id`` as the UIDAI org).

Enforcement resolves each rule to the set of eligible user ids via
user-management's ``/api/v3/authz/users`` discovery API (see
``app/services/document_access.py``). ``created_by`` is a logical FK to
``users.users.id``; ``deleted_at`` soft-clears a rule (clearing every rule
returns the document to PUBLIC).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DocumentAccessRule(Base):
    __tablename__ = "document_access_rules"
    __table_args__ = (
        Index("ix_document_access_rules_comment", "comment_id", "deleted_at"),
        Index("ix_document_access_rules_project", "project_id"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # The document = a body-NULL comment row (project.comments.id). Logical FK.
    comment_id: Mapped[str] = mapped_column(String(36))
    # The document's owning project — the default (project-scope) selector.
    project_id: Mapped[str] = mapped_column(String(36))
    # Role that is granted access, plus optional scope narrowers.
    role_name: Mapped[str] = mapped_column(String(64))
    organization_id: Mapped[Optional[str]] = mapped_column(String(36))
    division: Mapped[Optional[str]] = mapped_column(String(120))

    created_by: Mapped[str] = mapped_column(String(36))  # logical FK to users.users.id
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    # Soft-clear: a document with zero live rules is PUBLIC again.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
