"""TaskController."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories.task_repository import TaskRepository
from app.schemas.task import (
    TaskCreateRequest,
    TaskResourceSchema,
    TaskResponse,
    TaskUpdateRequest,
)
from app.services.task_service import TaskService


class TaskController:
    def __init__(self, db: Session):
        self.db = db
        self.service = TaskService(db)
        self.repo = TaskRepository(db)

    def _to_response(self, row) -> TaskResponse:
        resp = TaskResponse.model_validate(row)
        # Build displayCode: ``T<milestone.position>.<activity.position>.<task.position>``.
        from sqlalchemy import select
        from app.models.activity import Activity
        from app.models.milestone import Milestone
        ma_row = self.db.execute(
            select(Milestone.position, Activity.position)
            .select_from(Activity)
            .join(Milestone, Milestone.id == Activity.milestone_id)
            .where(Activity.id == row.activity_id)
        ).first()
        if ma_row and resp.position:
            m_pos, a_pos = ma_row
            if m_pos and a_pos:
                resp.display_code = f"T{m_pos}.{a_pos}.{resp.position}"
        # depends_on UUIDs + dependsOnDisplay (resolved to T<m>.<a>.<t> codes).
        dep_uuids = self.repo.list_dependencies_for(row.id)
        resp.depends_on = dep_uuids
        resp.depends_on_display = self._resolve_task_display_codes(
            row.project_id, dep_uuids,
        )
        # assignedToName from users.users mirror.
        if row.assigned_to:
            resp.assigned_to_name = self._resolve_assignee_name(row.assigned_to)
        resource_row = self.repo.get_resource(row.id)
        resp.resource = (
            TaskResourceSchema.model_validate(resource_row)
            if resource_row else None
        )
        # Multipart-arm /create may attach a freshly-created Comment row
        # on ``_inline_comment`` — surface as ``data.comment``.
        inline = getattr(row, "_inline_comment", None)
        if inline is not None:
            from app.controllers.comment_controller import CommentController
            resp.comment = CommentController(self.db)._to_response(inline)
        return resp

    def _resolve_task_display_codes(
        self, project_id: str, task_ids: List[str],
    ) -> List[str]:
        """Resolve task UUIDs to ``T<m_pos>.<a_pos>.<t_pos>`` labels scoped
        to the same project. Returns labels in the same order as the
        input UUIDs; unresolved UUIDs are skipped."""
        if not task_ids:
            return []
        from sqlalchemy import select
        from app.models.activity import Activity
        from app.models.milestone import Milestone
        from app.models.task import Task
        rows = self.db.execute(
            select(
                Task.id, Task.position, Activity.position, Milestone.position,
            )
            .join(Activity, Activity.id == Task.activity_id)
            .join(Milestone, Milestone.id == Activity.milestone_id)
            .where(Task.id.in_(task_ids))
            .where(Task.project_id == project_id)
            .where(Task.deleted_at.is_(None))
        ).all()
        by_id = {tid: (t_pos, a_pos, m_pos) for tid, t_pos, a_pos, m_pos in rows}
        out = []
        for tid in task_ids:
            t = by_id.get(tid)
            if t and t[0] and t[1] and t[2]:
                out.append(f"T{t[2]}.{t[1]}.{t[0]}")
        return out

    def _resolve_assignee_name(self, user_id: str) -> Optional[str]:
        """Look up display name from users.users mirror.

        Returns ``"<first> <last>"`` if both present, else first, else
        ``None``. Soft-deleted rows are still resolved (monolith parity —
        the historical assignment name remains visible)."""
        from sqlalchemy import select
        from app.models._cross_schema import User as MirrorUser
        row = self.db.execute(
            select(MirrorUser.full_name)
            .where(MirrorUser.id == user_id)
        ).first()
        if not row:
            return None
        return row[0] or None

    def get(self, task_id: str) -> TaskResponse:
        return self._to_response(self.service.get_by_id(task_id))

    def list_for_activity(
        self, activity_id: str, *, offset=1, page_size=50, include_deleted=False,
    ):
        rows, total = self.service.list_for_activity(
            activity_id, offset=offset, page_size=page_size,
            include_deleted=include_deleted,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def create(
        self,
        activity_id: str,
        payload: TaskCreateRequest,
        *, caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ):
        row = self.service.create(
            activity_id, payload,
            caller_user_id=caller_user_id,
            body=body, attachments=attachments,
        )
        return self._to_response(row)

    def update(
        self, task_id: str, payload: TaskUpdateRequest,
        *, caller_user_id: Optional[str], request=None,
    ):
        row = self.service.update(
            task_id, payload,
            caller_user_id=caller_user_id, request=request,
        )
        return self._to_response(row)

    def delete(self, task_id: str, *, caller_user_id: Optional[str]):
        row = self.service.delete(task_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def restore(self, task_id: str, *, caller_user_id: Optional[str]):
        row = self.service.restore(task_id, caller_user_id=caller_user_id)
        return self._to_response(row)
