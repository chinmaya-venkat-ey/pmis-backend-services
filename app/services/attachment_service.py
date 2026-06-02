"""AttachmentService — per-target multipart upload + attachment-listing.

Per-target endpoints store one comment row per upload with ``body=NULL``;
the JSONB ``attachments`` list carries the file metadata. Targets:
``project`` / ``milestone`` / ``activity`` / ``task`` / ``subtask`` —
the same polymorphism as the comment routes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.api_route import _camelize as _camelize_comment
from app.core.errors import NotFoundError, ValidationError
from app.models.comment import Comment
from app.repositories.activity_repository import ActivityRepository
from app.repositories.comment_repository import CommentRepository
from app.repositories.milestone_repository import MilestoneRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.subtask_repository import SubtaskRepository
from app.repositories.task_repository import TaskRepository
from app.utilities.multipart_form import (
    pre_validate_files,
    upload_files_via_client,
)


def _build_comment_hal(camel: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap a camelized comment dict as a full HAL Comment element.

    Mirrors the monolith's per-element shape inside the M/A/T/S
    attachment-list ``_embedded.elements`` array:
      * ``_type: "Comment"`` first
      * ``_links: {self, target}`` next — ``target.href`` uses the
        ``target_kind + "s"`` pluralisation quirk (yielding
        ``"activitys"`` for activity targets) — matched byte-for-byte.
    """
    cid = camel.get("id")
    target_kind = camel.get("targetKind")
    target_id = camel.get("targetId")
    links: Dict[str, Dict[str, str]] = {}
    if cid:
        links["self"] = {"href": f"/project/comments/{cid}"}
    if target_kind and target_id:
        links["target"] = {
            "href": f"/project/{target_kind}s/{target_id}",
            "title": target_kind,
        }
    out: Dict[str, Any] = {"_type": "Comment"}
    if links:
        out["_links"] = links
    out.update(camel)
    return out


class AttachmentService:
    def __init__(self, db: Session):
        self.db = db
        self.comments = CommentRepository(db)
        self.audit = ProjectAuditLogRepository(db)
        self.projects = ProjectRepository(db)
        self.milestones = MilestoneRepository(db)
        self.activities = ActivityRepository(db)
        self.tasks = TaskRepository(db)
        self.subtasks = SubtaskRepository(db)

    # ---------------------------------------------------- target resolution

    def _resolve_project_id(self, target_kind: str, target_id: str) -> str:
        """Look up the project_id under which the target lives.

        Monolith parity: NotFound message format SPLITS by target kind:
          * ``project`` -> ``"Project <uuid> not found."`` (capitalised
            kind, unquoted uuid — the project-attachment route uses this
            wording from ``ProjectController.get_attachments``).
          * ``milestone / activity / task / subtask`` ->
            ``"Target <kind> '<uuid>' not found."`` (literal ``Target``
            prefix, lowercase kind, quoted uuid — the M/A/T/S attachment
            routes route through ``comments._target_helper`` which uses
            that exact wording).

        The split mirrors a monolith inconsistency between the two
        modules. Both eventually 404 the same way, but the body strings
        diverge byte-for-byte and the FE sometimes surfaces them
        verbatim.
        """
        target_msg = lambda kind: f"Target {kind} '{target_id}' not found."  # noqa: E731
        if target_kind == "project":
            row = self.projects.get_by_id(target_id)
            if row is None:
                raise NotFoundError(f"Project {target_id} not found.")
            return row.id
        if target_kind == "milestone":
            row = self.milestones.get_by_id(target_id)
            if row is None:
                raise NotFoundError(target_msg("milestone"))
            return row.project_id
        if target_kind == "activity":
            row = self.activities.get_by_id(target_id)
            if row is None:
                raise NotFoundError(target_msg("activity"))
            return row.project_id
        if target_kind == "task":
            row = self.tasks.get_by_id(target_id)
            if row is None:
                raise NotFoundError(target_msg("task"))
            return row.project_id
        if target_kind == "subtask":
            row = self.subtasks.get_by_id(target_id)
            if row is None:
                raise NotFoundError(target_msg("subtask"))
            return row.project_id
        raise ValueError(f"unknown target_kind {target_kind!r}")

    # ------------------------------------------------------------- upload

    def upload_row(
        self,
        target_kind: str,
        target_id: str,
        files: List[UploadFile],
        *,
        caller_user_id: str,
    ) -> Comment:
        """Validate, write bytes, persist a body-NULL comment row, audit
        + commit, and return the freshly-created Comment row.

        The caller (controller) chooses the wire-shape:
          * project route wraps the row into the legacy Collection
            envelope via ``_envelope_response``.
          * M/A/T/S routes return the row as a Comment HAL envelope
            (monolith parity — POST emits a single Comment with the
            file metadata nested under ``attachments[]``).
        """
        project_id = self._resolve_project_id(target_kind, target_id)
        if not files:
            # No-files is a 422, not a 404. Prior implementation
            # incorrectly raised NotFoundError here.
            raise ValidationError("At least one file is required.")
        pre_validate_files(files)
        envelopes = upload_files_via_client(files)
        row = self.comments.create(
            target_kind=target_kind,
            target_id=target_id,
            author_user_id=caller_user_id,
            body=None,
            attachments=envelopes,
        )
        self.audit.write(
            project_id=project_id,
            target_kind="comment", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={
                "target_kind": target_kind,
                "target_id": target_id,
                "n_attachments": len(envelopes),
                "body_null": True,
            },
        )
        self.db.commit()
        return row

    def upload(
        self,
        target_kind: str,
        target_id: str,
        files: List[UploadFile],
        *,
        caller_user_id: str,
    ) -> Dict[str, Any]:
        """Project-attachment upload — returns the legacy Collection
        envelope. The controller still calls this for the project route.
        """
        row = self.upload_row(
            target_kind, target_id, files,
            caller_user_id=caller_user_id,
        )
        return self._envelope_response(row, row.attachments or [])

    # ----------------------------------------------------------- listings

    def list_for_target(
        self, target_kind: str, target_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ) -> Dict[str, Any]:
        """List body-IS-NULL comment rows under a target.

        Per-kind shape split (monolith parity):

        * ``project`` -> Collection with FLAT FILE-ROW elements (one
          element per file, fields ``{id, filename, url, mimeType,
          sizeBytes, uploadedAt, createdAt, createdBy}``). No
          ``pageSize`` / ``offset`` — project listing is one-screen.

        * ``milestone / activity / task / subtask`` -> Collection with
          full **Comment HAL** elements (one element per comment row,
          carrying the ``attachments[]`` JSON column inside). Top-level
          envelope adds ``pageSize`` + ``offset`` BEFORE ``_embedded``.
        """
        # Existence check on the parent target — surfaces a 404 instead
        # of returning an empty list silently.
        self._resolve_project_id(target_kind, target_id)
        rows, total = self.comments.list_attachments_for_target(
            target_kind, target_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        if target_kind == "project":
            return self._project_collection_envelope(rows)
        return self._target_collection_envelope(
            rows, total=total, offset=offset, page_size=page_size,
        )

    def _project_collection_envelope(
        self, rows: List[Comment],
    ) -> Dict[str, Any]:
        """Project-scope: flat-file-row elements, no pageSize/offset."""
        elements: List[Dict[str, Any]] = []
        for c in rows:
            for att in (c.attachments or []):
                elements.append({
                    "id": c.id,
                    "filename": att.get("filename"),
                    "url": att.get("url"),
                    "mime_type": att.get("mimeType") or att.get("mime_type"),
                    "size_bytes": att.get("sizeBytes") or att.get("size_bytes"),
                    "uploaded_at": att.get("uploadedAt") or att.get("uploaded_at"),
                    "created_at": c.created_at,
                    "created_by": c.author_user_id,
                })
        flat_count = len(elements)
        return {
            "_bare": True,
            "_type": "Collection",
            "total": flat_count,
            "count": flat_count,
            "_embedded": {"elements": elements},
        }

    def _target_collection_envelope(
        self,
        rows: List[Comment],
        *,
        total: int,
        offset: int,
        page_size: int,
    ) -> Dict[str, Any]:
        """M/A/T/S scope: full Comment HAL elements with pageSize/offset
        positioned BEFORE ``_embedded`` (monolith key order)."""
        from app.controllers.comment_controller import CommentController

        comment_ctrl = CommentController(self.db)
        elements: List[Dict[str, Any]] = []
        for c in rows:
            resp = comment_ctrl._to_response(c)
            camel = _camelize_comment(resp.model_dump(by_alias=False))
            elements.append(_build_comment_hal(camel))
        # Monolith parity: ``total`` and ``count`` are both the COMMENT
        # ROW count (each row is one element on the wire), not the
        # flattened file count. With singular ``file`` uploads the two
        # happen to coincide.
        return {
            "_bare": True,
            "_type": "Collection",
            "total": total,
            "count": len(elements),
            "pageSize": page_size,
            "offset": offset,
            "_embedded": {"elements": elements},
        }

    def list_for_project(self, project_id: str) -> Dict[str, Any]:
        """Project-scoped listing for ``GET /project/projects/{uuid}/attachments``.

        Lists every comment row under ``target_kind='project'`` for the
        project. Files-only: every row has ``body IS NULL``.
        """
        if self.projects.get_by_id(project_id) is None:
            raise NotFoundError(f"Project {project_id} not found.")
        # Reuse the per-target listing — pagination forced to a big page
        # since the FE renders all on one screen (mirrors monolith).
        return self.list_for_target(
            "project", project_id, offset=1, page_size=500,
        )

    # ------------------------------------------------------------- helper

    def _envelope_response(self, row, envelopes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Monolith parity: upload response is itself a Collection
        envelope — ``{_type: "Collection", total, count, _embedded:
        {elements: [...]}}`` — NOT a bare ``{total, elements}``. The
        ``_bare: True`` marker tells the wrap layer to pass the dict
        through unchanged (so no extra ``_type: "Resource"`` is added).
        """
        elements: List[Dict[str, Any]] = []
        for att in envelopes:
            elements.append({
                "id": row.id,
                "filename": att.get("filename"),
                "url": att.get("url"),
                "mime_type": att.get("mimeType"),
                "size_bytes": att.get("sizeBytes"),
                "uploaded_at": att.get("uploadedAt"),
                "created_at": row.created_at,
                "created_by": row.author_user_id,
            })
        flat_count = len(elements)
        return {
            "_bare": True,
            "_type": "Collection",
            "total": flat_count,
            "count": flat_count,
            "_embedded": {"elements": elements},
        }
