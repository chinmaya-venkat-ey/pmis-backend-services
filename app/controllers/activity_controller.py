"""ActivityController."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories.activity_repository import ActivityRepository
from app.schemas.activity import (
    ActivityCompletionEligibilityResponse,
    ActivityCreateRequest,
    ActivityResourceSchema,
    ActivityResponse,
    ActivityUpdateRequest,
)
from app.services.activity_service import ActivityService


class ActivityController:
    def __init__(self, db: Session):
        self.db = db
        self.service = ActivityService(db)
        self.repo = ActivityRepository(db)

    def _to_response(self, row) -> ActivityResponse:
        resp = ActivityResponse.model_validate(row)
        # Map ``concerned_divisions`` (plural model column) to
        # ``concerned_division`` (singular Python attribute → singular
        # wire alias ``concernedDivision`` after camelize). Source list
        # is preserved as-is — only the attribute name changes.
        resp.concerned_division = getattr(row, "concerned_divisions", None)
        # Build displayCode: ``A<milestone.position>.<activity.position>``.
        from app.models.milestone import Milestone
        from sqlalchemy import select
        m_pos = self.db.execute(
            select(Milestone.position).where(Milestone.id == row.milestone_id)
        ).scalar()
        if m_pos and resp.position:
            resp.display_code = f"A{m_pos}.{resp.position}"
        # depends_on UUIDs + dependsOnDisplay (resolved to A<m>.<a> codes).
        dep_uuids = self.repo.list_dependencies_for(row.id)
        resp.depends_on = dep_uuids
        resp.depends_on_display = self._resolve_activity_display_codes(
            row.project_id, dep_uuids,
        )
        resource_row = self.repo.get_resource(row.id)
        resp.resource = (
            ActivityResourceSchema.model_validate(resource_row)
            if resource_row else None
        )
        # Multipart-arm /create may attach a freshly-created Comment row
        # on ``_inline_comment`` — surface as ``data.comment``.
        inline = getattr(row, "_inline_comment", None)
        if inline is not None:
            from app.controllers.comment_controller import CommentController
            resp.comment = CommentController(self.db)._to_response(inline)
        return resp

    def _resolve_activity_display_codes(
        self, project_id: str, activity_ids: List[str],
    ) -> List[str]:
        """Resolve activity UUIDs to ``A<m_pos>.<a_pos>`` labels scoped
        to the same project. Returns labels in the same order as the
        input UUIDs; unresolved UUIDs are skipped."""
        if not activity_ids:
            return []
        from sqlalchemy import select
        from app.models.activity import Activity
        from app.models.milestone import Milestone
        rows = self.db.execute(
            select(
                Activity.id, Activity.position, Milestone.position,
            )
            .join(Milestone, Milestone.id == Activity.milestone_id)
            .where(Activity.id.in_(activity_ids))
            .where(Activity.project_id == project_id)
            .where(Activity.deleted_at.is_(None))
        ).all()
        by_id = {aid: (a_pos, m_pos) for aid, a_pos, m_pos in rows}
        out = []
        for aid in activity_ids:
            t = by_id.get(aid)
            if t and t[0] and t[1]:
                out.append(f"A{t[1]}.{t[0]}")
        return out

    def get(self, activity_id: str) -> ActivityResponse:
        return self._to_response(self.service.get_by_id(activity_id))

    def completion_eligibility(
        self, activity_id: str,
    ) -> ActivityCompletionEligibilityResponse:
        result = self.service.completion_eligibility(activity_id)
        return ActivityCompletionEligibilityResponse.model_validate(result)

    def list_for_milestone(
        self, milestone_id: str, *, offset=1, page_size=50, include_deleted=False,
    ):
        rows, total = self.service.list_for_milestone(
            milestone_id, offset=offset, page_size=page_size,
            include_deleted=include_deleted,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def create(
        self,
        milestone_id: str,
        payload: ActivityCreateRequest,
        *, caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ):
        row = self.service.create(
            milestone_id, payload,
            caller_user_id=caller_user_id,
            body=body, attachments=attachments,
        )
        return self._to_response(row)

    def update(
        self, activity_id: str, payload: ActivityUpdateRequest,
        *, caller_user_id: Optional[str], request=None,
    ):
        row = self.service.update(
            activity_id, payload,
            caller_user_id=caller_user_id, request=request,
        )
        return self._to_response(row)

    def delete(self, activity_id: str, *, caller_user_id: Optional[str]):
        row = self.service.delete(activity_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def restore(self, activity_id: str, *, caller_user_id: Optional[str]):
        row = self.service.restore(activity_id, caller_user_id=caller_user_id)
        return self._to_response(row)
