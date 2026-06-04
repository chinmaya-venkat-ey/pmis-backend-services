"""SubtaskController."""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.repositories.subtask_repository import SubtaskRepository
from app.schemas.subtask import (
    SubtaskCreateRequest,
    SubtaskResourceSchema,
    SubtaskResponse,
    SubtaskUpdateRequest,
)
from app.services.subtask_service import SubtaskService


class SubtaskController:
    def __init__(self, db: Session):
        self.db = db
        self.service = SubtaskService(db)
        self.repo = SubtaskRepository(db)

    # ------------------------------------------------------- response build

    def _to_response(self, row, *, mat_chain=None) -> SubtaskResponse:
        """Build a SubtaskResponse for a single row.

        ``mat_chain`` is an optional pre-fetched ``(m_pos, a_pos, t_pos)``
        tuple from the owning task's parent chain — passing it from the
        list path avoids a per-row join. When omitted, the chain is
        fetched here for single-resource paths.
        """
        resp = SubtaskResponse.model_validate(row)
        if mat_chain is None:
            mat_chain = self._fetch_mat_chain(row.task_id)
        # displayCode = "S<m>.<a>.<t>.<positions from root subtask down to this row>".
        # Top-level: 4 segments. Each nesting level appends one more.
        positions = self._walk_parent_positions(row)
        if mat_chain and positions and all(mat_chain):
            m_pos, a_pos, t_pos = mat_chain
            parts = [f"S{m_pos}", str(a_pos), str(t_pos)] + [str(p) for p in positions]
            resp.display_code = ".".join(parts)
        # depends_on UUIDs + dependsOnDisplay (resolved via subtask_service
        # helper which already handles nested chain).
        dep_uuids = self.repo.list_dependencies_for(row.id)
        resp.depends_on = dep_uuids
        if dep_uuids:
            codes = self.service._batch_resolve_display_codes(dep_uuids)
            resp.depends_on_display = [
                codes[uid] for uid in dep_uuids if uid in codes
            ]
        else:
            resp.depends_on_display = []
        if row.assigned_to:
            resp.assigned_to_name = self._resolve_assignee_name(row.assigned_to)
        resource_row = self.repo.get_resource(row.id)
        resp.resource = (
            SubtaskResourceSchema.model_validate(resource_row)
            if resource_row else None
        )
        # Multipart-arm /create may attach a freshly-created Comment row
        # on ``_inline_comment`` — surface as ``data.comment``.
        inline = getattr(row, "_inline_comment", None)
        if inline is not None:
            from app.controllers.comment_controller import CommentController
            resp.comment = CommentController(self.db)._to_response(inline)
        return resp

    # ------------------------------------------------------- helpers

    def _fetch_mat_chain(self, task_id: str):
        """Return ``(milestone.position, activity.position, task.position)``
        for the task that owns this subtask. ``None`` if any join row
        is missing."""
        from sqlalchemy import select
        from app.models.activity import Activity
        from app.models.milestone import Milestone
        from app.models.task import Task
        return self.db.execute(
            select(Milestone.position, Activity.position, Task.position)
            .select_from(Task)
            .join(Activity, Activity.id == Task.activity_id)
            .join(Milestone, Milestone.id == Activity.milestone_id)
            .where(Task.id == task_id)
        ).first()

    def _walk_parent_positions(self, row) -> List[int]:
        """Walk parent_subtask_id chain up to the root top-level subtask
        and return positions in ROOT → THIS order. For a top-level
        subtask this is just ``[row.position]``."""
        from sqlalchemy import select
        from app.models.subtask import Subtask
        positions = [row.position]
        current_parent = row.parent_subtask_id
        seen: set[str] = set()
        while current_parent and current_parent not in seen:
            seen.add(current_parent)
            parent = self.db.execute(
                select(Subtask.position, Subtask.parent_subtask_id)
                .where(Subtask.id == current_parent)
            ).first()
            if not parent or not parent[0]:
                break
            positions.insert(0, parent[0])
            current_parent = parent[1]
        return positions

    def _resolve_assignee_name(self, user_id: str) -> Optional[str]:
        """Look up display name from users.users mirror."""
        from sqlalchemy import select
        from app.models._cross_schema import User as MirrorUser
        row = self.db.execute(
            select(MirrorUser.first_name, MirrorUser.last_name)
            .where(MirrorUser.id == user_id)
        ).first()
        if not row:
            return None
        first, last = row
        parts = [p for p in (first, last) if p]
        return " ".join(parts) if parts else None

    # ------------------------------------------------------- endpoints

    def get(self, subtask_id: str) -> SubtaskResponse:
        # Single GET: leave ``subtasks`` as None — the wrap layer drops the
        # key so the wire shape matches the monolith's flat single-read.
        return self._to_response(self.service.get_by_id(subtask_id))

    def list_for_task(
        self, task_id: str, *,
        offset=1, page_size=100,
        include_deleted=False, top_level_only=False,  # NOSONAR(S1172): kept for monolith-parity call site
    ):
        """Monolith parity: returns TOP-LEVEL subtasks only and embeds
        each subtask's nested descendants under a ``subtasks: [...]``
        recursive array. ``total`` reflects top-level count.

        Implementation: one query for every live subtask under the task,
        bucket by ``parent_subtask_id``, then recurse.
        """
        from sqlalchemy import and_, select
        from app.models.subtask import Subtask
        mat_chain = self._fetch_mat_chain(task_id)
        clauses = [Subtask.task_id == task_id]
        if not include_deleted:
            clauses.append(Subtask.deleted_at.is_(None))
        all_rows = list(self.db.execute(
            select(Subtask).where(and_(*clauses)).order_by(Subtask.position.asc())
        ).scalars())
        # Bucket nested rows by parent_subtask_id for O(1) child lookup.
        by_parent: Dict[Optional[str], List] = {}
        for r in all_rows:
            by_parent.setdefault(r.parent_subtask_id, []).append(r)
        top_level = by_parent.get(None, [])
        total = len(top_level)

        def build(r):
            resp = self._to_response(r, mat_chain=mat_chain)
            children = by_parent.get(r.id, [])
            resp.subtasks = [build(c) for c in children]
            return resp

        start = max(0, offset - 1) * page_size
        page = top_level[start : start + page_size]
        return {
            "items": [build(r) for r in page],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def create_under_task(
        self,
        task_id: str,
        payload: SubtaskCreateRequest,
        *, caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ):
        row = self.service.create(
            payload, task_id=task_id,
            caller_user_id=caller_user_id,
            body=body, attachments=attachments,
        )
        return self._to_response(row)

    def create_nested(
        self,
        parent_subtask_id: str,
        payload: SubtaskCreateRequest,
        *, caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ):
        row = self.service.create(
            payload, parent_subtask_id=parent_subtask_id,
            caller_user_id=caller_user_id,
            body=body, attachments=attachments,
        )
        return self._to_response(row)

    def update(
        self, subtask_id: str, payload: SubtaskUpdateRequest,
        *, caller_user_id: Optional[str], request=None,
    ):
        row = self.service.update(
            subtask_id, payload,
            caller_user_id=caller_user_id, request=request,
        )
        return self._to_response(row)

    def delete(self, subtask_id: str, *, caller_user_id: Optional[str]):
        row = self.service.delete(subtask_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def restore(self, subtask_id: str, *, caller_user_id: Optional[str]):
        row = self.service.restore(subtask_id, caller_user_id=caller_user_id)
        return self._to_response(row)
