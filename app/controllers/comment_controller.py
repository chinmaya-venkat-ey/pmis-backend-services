"""CommentController — polymorphic comments across 5 targets:
``project`` / ``milestone`` / ``activity`` / ``task`` / ``subtask``.

Create accepts both JSON (legacy) and multipart (body Form field +
``files`` UploadFile entries). The multipart path streams each file
through the file client and inlines the resulting URL envelopes on the
comment row.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.repositories.activity_repository import ActivityRepository
from app.repositories.milestone_repository import MilestoneRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.subtask_repository import SubtaskRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.comment import (
    CommentAuthor,
    CommentCreateRequest,
    CommentDeleteSuccess,
    CommentResponse,
)
from app.services.comment_service import CommentService
from app.utilities.multipart_form import (
    pre_validate_files,
    upload_files_via_client,
)


class CommentController:
    def __init__(self, db: Session):
        self.db = db
        self.service = CommentService(db)
        self._projects = ProjectRepository(db)
        self._milestones = MilestoneRepository(db)
        self._activities = ActivityRepository(db)
        self._tasks = TaskRepository(db)
        self._subtasks = SubtaskRepository(db)

    # ----------------------------------------------------- target lookup

    def resolve_project_id(self, target_kind: str, target_id: str) -> str:
        """Look up the project_id of a comment's target. Raises 404 with
        the monolith-format message ``"Target <kind> '<uuid>' not found."``
        — distinct wording from the parent module's own NotFound, but
        what the monolith returns on /<kind>/<id>/comments paths.
        """
        msg = lambda kind: f"Target {kind} '{target_id}' not found."  # noqa: E731
        if target_kind == "project":
            row = self._projects.get_by_id(target_id)
            if row is None:
                raise NotFoundError(msg("project"))
            return row.id
        if target_kind == "milestone":
            row = self._milestones.get_by_id(target_id)
            if row is None:
                raise NotFoundError(msg("milestone"))
            return row.project_id
        if target_kind == "activity":
            row = self._activities.get_by_id(target_id)
            if row is None:
                raise NotFoundError(msg("activity"))
            return row.project_id
        if target_kind == "task":
            row = self._tasks.get_by_id(target_id)
            if row is None:
                raise NotFoundError(msg("task"))
            return row.project_id
        if target_kind == "subtask":
            row = self._subtasks.get_by_id(target_id)
            if row is None:
                raise NotFoundError(msg("subtask"))
            return row.project_id
        raise ValueError(f"unknown target_kind {target_kind!r}")

    # -------------------------------------------------- response builder

    def _to_response(self, row) -> CommentResponse:
        """Build the wire-shape for a comment row. Resolves the nested
        ``author`` object from the cross-schema user mirror and
        normalises a NULL ``attachments`` column to ``[]`` so the wire
        always carries the field (monolith parity)."""
        resp = CommentResponse.model_validate(row)
        if row.attachments is None:
            resp.attachments = []
        if row.author_user_id:
            resp.author = self._resolve_author(row.author_user_id)
        return resp

    def _resolve_author(self, user_id: str) -> Optional[CommentAuthor]:
        """Look up ``users.users`` mirror and build the
        ``{id, login, fullName, email}`` object. Returns a
        minimal author with just the id when the user row is missing
        (deleted users still appear on historical comments)."""
        from sqlalchemy import select
        from app.models._cross_schema import User as MirrorUser
        row = self.db.execute(
            select(
                MirrorUser.id, MirrorUser.login, MirrorUser.email,
                MirrorUser.full_name,
            )
            .where(MirrorUser.id == user_id)
        ).first()
        if not row:
            return CommentAuthor(id=user_id)
        uid, login, email, full_name = row
        return CommentAuthor(
            id=uid, login=login, email=email, full_name=full_name,
        )

    # --------------------------------------------------------------- list

    def list_for_target(
        self, target_kind: str, target_id: str, *,
        offset=1, page_size=50, include_deleted=False,
    ) -> Dict[str, Any]:
        # Verify the target exists so we 404 on bad ids instead of empty list.
        self.resolve_project_id(target_kind, target_id)
        rows, total = self.service.list_for_target(
            target_kind, target_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    # ---------------------------------------------------------- get by id

    def get(self, comment_id: str) -> CommentResponse:
        """Resolve one comment/attachment row by its OWN id (not by
        target). Serves both regular comments and attachment-only
        (``body IS NULL``) document rows — the resolved envelope carries
        the file metadata under ``attachments[]``. The service 404s on a
        missing or soft-deleted id (``"Comment <uuid> not found."``),
        matching the monolith.
        """
        row = self.service.get_by_id(comment_id)
        return self._to_response(row)

    # ------------------------------------------------------------- create

    def create_json(
        self,
        *,
        target_kind: str,
        target_id: str,
        payload: CommentCreateRequest,
        caller_user_id: str,
    ) -> CommentResponse:
        project_id = self.resolve_project_id(target_kind, target_id)
        atts = (
            [a.model_dump(by_alias=True) for a in payload.attachments]
            if payload.attachments else None
        )
        row = self.service.create(
            project_id=project_id,
            target_kind=target_kind,
            target_id=target_id,
            body=payload.body,
            attachments=atts,
            caller_user_id=caller_user_id,
        )
        return self._to_response(row)

    def create_multipart(
        self,
        *,
        target_kind: str,
        target_id: str,
        body: Optional[str],
        files: List[UploadFile],
        caller_user_id: str,
    ) -> CommentResponse:
        project_id = self.resolve_project_id(target_kind, target_id)
        pre_validate_files(files)
        envelopes = upload_files_via_client(files) if files else []
        row = self.service.create(
            project_id=project_id,
            target_kind=target_kind,
            target_id=target_id,
            body=body,
            attachments=envelopes if envelopes else None,
            caller_user_id=caller_user_id,
        )
        return self._to_response(row)

    # ------------------------------------------------------------- delete

    def delete(
        self, comment_id: str, *,
        caller_user_id: str, caller_is_admin: bool,
        caller_permissions: Optional[set] = None,
    ) -> CommentDeleteSuccess:
        """Monolith parity: returns a ``Success`` envelope, NOT the full
        Comment row. The soft-delete state is captured in ``deleted_at``
        + ``deleted_by`` on the DB row (kept for audit / restore)."""
        # Resolve project_id for audit attribution.
        existing = self.service.get_by_id(comment_id)
        project_id: Optional[str] = None
        try:
            project_id = self.resolve_project_id(
                existing.target_kind, existing.target_id,
            )
        except NotFoundError:
            project_id = None
        self.service.delete(
            comment_id,
            caller_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
            caller_permissions=caller_permissions,
            project_id=project_id,
        )
        return CommentDeleteSuccess(
            message=f"Comment {comment_id} deleted.",
        )
