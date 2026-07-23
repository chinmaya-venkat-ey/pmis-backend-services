"""DocumentAccessRuleRepository — CRUD for #323 per-document access rules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Sequence

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.document_access_rule import DocumentAccessRule


class DocumentAccessRuleRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_comment(self, comment_id: str) -> List[DocumentAccessRule]:
        """Live rules for one document (newest first)."""
        stmt = (
            select(DocumentAccessRule)
            .where(
                and_(
                    DocumentAccessRule.comment_id == comment_id,
                    DocumentAccessRule.deleted_at.is_(None),
                )
            )
            .order_by(DocumentAccessRule.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def map_for_comments(
        self, comment_ids: Sequence[str],
    ) -> Dict[str, List[DocumentAccessRule]]:
        """Live rules for many documents → ``{comment_id: [rules]}``.

        Only documents that actually have a rule appear as keys, so callers can
        treat a missing key as PUBLIC.
        """
        ids = [c for c in set(comment_ids) if c]
        if not ids:
            return {}
        stmt = select(DocumentAccessRule).where(
            and_(
                DocumentAccessRule.comment_id.in_(ids),
                DocumentAccessRule.deleted_at.is_(None),
            )
        )
        out: Dict[str, List[DocumentAccessRule]] = {}
        for rule in self.db.execute(stmt).scalars().all():
            out.setdefault(rule.comment_id, []).append(rule)
        return out

    def replace_for_comment(
        self,
        comment_id: str,
        project_id: str,
        rules: Iterable[dict],
        *,
        created_by: str,
    ) -> List[DocumentAccessRule]:
        """Soft-clear the document's existing rules and insert ``rules``.

        Each rule dict: ``{role_name, organization_id?, division?}``. An empty
        ``rules`` clears every rule → the document becomes PUBLIC again. Caller
        commits.
        """
        now = datetime.now(timezone.utc)
        for existing in self.list_for_comment(comment_id):
            existing.deleted_at = now
        created: List[DocumentAccessRule] = []
        for r in rules:
            role_name = (r.get("role_name") or "").strip()
            if not role_name:
                continue
            row = DocumentAccessRule(
                comment_id=comment_id,
                project_id=project_id,
                role_name=role_name,
                organization_id=(r.get("organization_id") or None),
                division=(r.get("division") or None),
                created_by=created_by,
            )
            self.db.add(row)
            created.append(row)
        self.db.flush()
        return created
