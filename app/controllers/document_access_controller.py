"""#323 — management controller for per-document role-based access.

Superadmin/admin only (gated at the route). Lets an admin see a target's
documents newest-first and set/replace/clear each document's role rules.
Enforcement of those rules lives in ``app/services/document_access.py``.
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.repositories.comment_repository import CommentRepository
from app.repositories.document_access_rule_repository import (
    DocumentAccessRuleRepository,
)
from app.schemas.document_access import (
    DocumentAccessList,
    DocumentAccessListItem,
    DocumentAccessResponse,
    DocumentAccessRuleView,
    DocumentAccessUpdateRequest,
)


class DocumentAccessController:
    def __init__(self, db: Session):
        self.db = db
        self.comments = CommentRepository(db)
        self.rules = DocumentAccessRuleRepository(db)

    # -------------------------------------------------------------- helpers

    def _require_document(self, comment_id: str):
        row = self.comments.get_by_id(comment_id)
        if row is None or row.deleted_at is not None:
            raise NotFoundError(f"Document {comment_id} not found.")
        return row

    def _project_id_for(self, row) -> str:
        """The owning project of a comment/attachment row."""
        if row.target_kind == "project":
            return row.target_id
        from app.core.rbac import _ancestor_project_id
        return _ancestor_project_id(f"{row.target_kind}_id", row.target_id) or ""

    @staticmethod
    def _rule_views(rules) -> List[DocumentAccessRuleView]:
        return [
            DocumentAccessRuleView(
                role_name=r.role_name,
                organization_id=r.organization_id,
                division=r.division,
            )
            for r in rules
        ]

    # ---------------------------------------------------------------- reads

    def get_access(self, comment_id: str) -> DocumentAccessResponse:
        self._require_document(comment_id)
        rules = self.rules.list_for_comment(comment_id)
        return DocumentAccessResponse(
            comment_id=comment_id,
            is_restricted=bool(rules),
            rules=self._rule_views(rules),
        )

    def list_access(self, target_kind: str, target_id: str) -> DocumentAccessList:
        """Every document under a target, NEWEST-FIRST, with its access state."""
        rows, _ = self.comments.list_attachments_for_target(
            target_kind, target_id, offset=1, page_size=500, include_deleted=False,
        )
        # list_attachments_for_target is oldest-first; the menu wants latest-added
        # documents first.
        rows = sorted(rows, key=lambda r: r.created_at, reverse=True)
        rules_by_comment = self.rules.map_for_comments([r.id for r in rows])
        items: List[DocumentAccessListItem] = []
        for r in rows:
            first = (r.attachments or [{}])[0] if (r.attachments) else {}
            rules = rules_by_comment.get(r.id, [])
            items.append(DocumentAccessListItem(
                comment_id=r.id,
                filename=first.get("filename"),
                url=first.get("url"),
                created_at=r.created_at,
                uploaded_by=r.author_user_id,
                is_restricted=bool(rules),
                rules=self._rule_views(rules),
            ))
        return DocumentAccessList(
            target_kind=target_kind, target_id=target_id, documents=items,
        )

    # --------------------------------------------------------------- writes

    def set_access(
        self, comment_id: str, payload: DocumentAccessUpdateRequest, *,
        caller_user_id: str,
    ) -> DocumentAccessResponse:
        row = self._require_document(comment_id)
        project_id = self._project_id_for(row)
        rule_dicts = [
            {
                "role_name": e.role_name,
                "organization_id": e.organization_id,
                "division": e.division,
            }
            for e in payload.rules
        ]
        self.rules.replace_for_comment(
            comment_id, project_id, rule_dicts, created_by=caller_user_id,
        )
        self.db.commit()
        rules = self.rules.list_for_comment(comment_id)
        return DocumentAccessResponse(
            comment_id=comment_id,
            is_restricted=bool(rules),
            rules=self._rule_views(rules),
        )
