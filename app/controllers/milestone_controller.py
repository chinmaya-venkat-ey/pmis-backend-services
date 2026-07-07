"""MilestoneController."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories.milestone_repository import MilestoneRepository
from app.schemas.milestone import (
    MilestoneCreateRequest,
    MilestoneResponse,
    MilestoneUpdateRequest,
)
from app.services.milestone_service import MilestoneService


class MilestoneController:
    def __init__(self, db: Session):
        self.db = db
        self.service = MilestoneService(db)
        self.repo = MilestoneRepository(db)

    def _to_response(self, row) -> MilestoneResponse:
        resp = MilestoneResponse.model_validate(row)
        # ``displayCode`` mirrors monolith's per-project sequential label
        # (M1 / M2 / M3 / …). Position is auto-assigned at create-time
        # in monolith order so this is a direct mapping.
        if resp.position:
            resp.display_code = f"M{resp.position}"
        # Resolve UUID deps to their target milestones' display codes.
        dep_uuids = self.repo.list_dependencies_for(row.id)
        resp.depends_on = dep_uuids
        resp.depends_on_display = self._resolve_milestone_display_codes(
            row.project_id, dep_uuids,
        )
        # Monolith milestone response always returns an empty vendors
        # list (vendor association isn't surfaced on the milestone row).
        resp.vendors = []
        # Multipart-arm /create stashes the first comment on a transient
        # ``_inline_comment`` attribute; surface it as ``data.comment``
        # so the wire matches monolith. JSON-arm + all subsequent reads
        # leave the attribute absent and the field stays ``None`` (wrap
        # layer drops the key).
        inline = getattr(row, "_inline_comment", None)
        if inline is not None:
            from app.controllers.comment_controller import CommentController
            resp.comment = CommentController(self.db)._to_response(inline)
        return resp

    def _resolve_milestone_display_codes(
        self, project_id: str, milestone_ids: List[str],
    ) -> List[str]:
        """Look up M<position> labels for the supplied milestone UUIDs.
        Same-project targets render unchanged; cross-project targets are
        prefixed with their project NAME (``<name> · M<n>``). Returns the
        labels in the same order as ``milestone_ids``; an unresolved UUID is
        dropped."""
        if not milestone_ids:
            return []
        from sqlalchemy import select
        from app.models.milestone import Milestone
        from app.models.project import Project
        rows = self.db.execute(
            select(
                Milestone.id, Milestone.position,
                Milestone.project_id, Project.name,
            )
            .join(Project, Project.id == Milestone.project_id)
            .where(Milestone.id.in_(milestone_ids))
            .where(Milestone.deleted_at.is_(None))
        ).all()
        by_id = {mid: (pos, proj_id, name) for mid, pos, proj_id, name in rows}
        out = []
        for mid in milestone_ids:
            t = by_id.get(mid)
            if t and t[0]:
                pos, proj_id, name = t
                label = f"M{pos}"
                if proj_id != project_id:
                    label = f"{name} · {label}"
                out.append(label)
        return out

    def get(self, milestone_id: str, *, caller_vendor_id=None, caller_is_admin=True) -> MilestoneResponse:
        return self._to_response(self.service.get_by_id(
            milestone_id, caller_vendor_id=caller_vendor_id, caller_is_admin=caller_is_admin))

    def list_for_project(
        self, project_id: str, *, offset=1, page_size=50, include_deleted=False,
        caller_vendor_id=None, caller_is_admin=True,
    ):
        rows, total = self.service.list_for_project(
            project_id, offset=offset, page_size=page_size,
            include_deleted=include_deleted,
            caller_vendor_id=caller_vendor_id, caller_is_admin=caller_is_admin,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def create(
        self,
        project_id: str,
        payload: MilestoneCreateRequest,
        *, caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ) -> MilestoneResponse:
        row = self.service.create(
            project_id, payload,
            caller_user_id=caller_user_id,
            body=body, attachments=attachments,
        )
        return self._to_response(row)

    def update(
        self, milestone_id: str, payload: MilestoneUpdateRequest,
        *, caller_user_id: Optional[str], request=None,
    ) -> MilestoneResponse:
        row = self.service.update(
            milestone_id, payload,
            caller_user_id=caller_user_id, request=request,
        )
        return self._to_response(row)

    def delete(self, milestone_id: str, *, caller_user_id: Optional[str]) -> MilestoneResponse:
        row = self.service.delete(milestone_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def restore(self, milestone_id: str, *, caller_user_id: Optional[str]) -> MilestoneResponse:
        row = self.service.restore(milestone_id, caller_user_id=caller_user_id)
        return self._to_response(row)
