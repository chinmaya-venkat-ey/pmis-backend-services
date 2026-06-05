"""ProjectController — orchestrates ProjectService + extra reads for the
project-scoped sub-routes (audit-logs, discussion-feed, role-assignments,
assignable-users, attachments)."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import Division as _DivisionMirror, Vendor as _VendorMirror
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import (
    ProjectCloseRequest,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    ProjectUpsertRequest,
)
from app.services.assignable_users_service import AssignableUsersService
from app.services.attachment_service import AttachmentService
from app.services.audit_log_service import AuditLogService
from app.services.discussion_feed_service import DiscussionFeedService
from app.services.project_service import ProjectService


class ProjectController:
    def __init__(self, db: Session):
        self.db = db
        self.service = ProjectService(db)
        self.repo = ProjectRepository(db)
        self.audit_log_svc = AuditLogService(db)
        self.discussion = DiscussionFeedService(db)
        self.assignable = AssignableUsersService(db)
        self.attachments = AttachmentService(db)

    # --------------------------------------------------- response shaping

    def _to_response(
        self, row, *, with_attachments: bool = False,
        ensure_meeting_milestone: bool = False,
        caller_user_id: Optional[str] = None,
    ) -> ProjectResponse:
        """Build the wire response for a single project.

        Monolith parity: only the GET single-project endpoint includes
        ``attachments``. All other endpoints (create / patch / upsert /
        save / publish / close / list) leave the field as None — the
        HAL wrap layer drops the key entirely when None so the wire
        body matches monolith exactly.

        2026-06-03 — ``meeting_milestone_id`` is populated for every
        response. When ``ensure_meeting_milestone=True`` AND the project
        is published, the JIT path lazily creates the hidden meeting
        milestone if it's missing (covers projects published before the
        feature shipped). When False, the field is read-only — the
        controller doesn't write through the response shaper.
        """
        resp = ProjectResponse.model_validate(row)
        # ``isPublic`` mirrors ``public`` on the wire.
        resp.is_public = bool(getattr(row, "public", False))
        vendor_ids = self.repo.list_vendors_for_project(row.id)
        resp.vendors = self._hydrate_vendor_chips(vendor_ids)
        # Resolve owner_label from masters.divisions mirror so the FE has a
        # human-readable label without a separate /master/divisions call.
        resp.owner_label = self._resolve_owner_label(resp.owner)
        # Doc-finance: derive inclusive-tax companion on every response.
        # The model never stores this — it's computed from excl-tax + tax%
        # by app/utilities/ccn_calc.py so the same rounding applies
        # everywhere on the wire.
        from app.utilities import ccn_calc
        resp.total_project_value_incl_tax = ccn_calc.total_project_value_incl_tax(
            getattr(row, "total_project_value_excl_tax", 0),
            getattr(row, "tax_percent", 0),
        )
        # 2026-06-03 — meeting milestone id (hidden container for meeting
        # activities). Always read first; lazily create on the
        # project-detail path only.
        resp.meeting_milestone_id = self._resolve_meeting_milestone_id(
            row, ensure=ensure_meeting_milestone, caller_user_id=caller_user_id,
        )
        if with_attachments:
            resp.attachments = self._hydrate_attachments(row.id)
        return resp

    def _resolve_meeting_milestone_id(
        self, project, *, ensure: bool, caller_user_id: Optional[str],
    ) -> Optional[str]:
        """Return the id of the project's meeting milestone if one exists.

        When ``ensure=True`` AND the project is published, lazily create
        one if absent (covers projects published before the meeting-
        milestone feature shipped). Reads come for free either way.
        """
        existing = self.service.milestones.get_meeting_milestone_id(project.id)
        if existing is not None:
            return existing
        if not ensure:
            return None
        if (getattr(project, "status", None) or "").lower() != "published":
            return None
        # JIT create. The service helper does its own existence check, so
        # this is safe even under concurrent detail fetches.
        new_id = self.service._ensure_meeting_milestone(
            project, caller_user_id=caller_user_id,
        )
        if new_id is not None:
            self.db.commit()
        return new_id

    def _resolve_owner_label(self, owner_code: Optional[str]) -> Optional[str]:
        """Look up the division label for the project owner via the
        masters.divisions cross-schema mirror. Returns None when the owner
        is null, "others", or an unknown code."""
        if not owner_code or owner_code.lower() == "others":
            return None
        div = self.db.execute(
            select(_DivisionMirror).where(_DivisionMirror.code == owner_code)
        ).scalars().first()
        return div.label if div is not None else None

    def _hydrate_attachments(self, project_id: str):
        """Pull every ``body IS NULL`` comment row under
        ``target_kind='project'`` and shape into the monolith attachment
        list. Called only from ``get()`` (GET /projects/{uuid})."""
        from app.repositories.comment_repository import CommentRepository
        from app.schemas.attachment import AttachmentRow

        comments_repo = CommentRepository(self.db)
        rows, _total = comments_repo.list_attachments_for_target(
            "project", project_id, offset=1, page_size=500,
        )
        out = []
        for c in rows:
            for att in (c.attachments or []):
                out.append(AttachmentRow(
                    id=c.id,
                    filename=att.get("filename"),
                    url=att.get("url"),
                    mime_type=att.get("mimeType") or att.get("mime_type"),
                    size_bytes=att.get("sizeBytes") or att.get("size_bytes"),
                    uploaded_at=att.get("uploadedAt") or att.get("uploaded_at"),
                    created_at=c.created_at,
                    created_by=c.author_user_id,
                ))
        return out

    def _hydrate_vendor_chips(self, vendor_ids):
        """Bulk-resolve ``vendor_ids`` → ``[{id, name}, ...]`` via the
        ``masters.vendors`` cross-schema mirror. Returns ``[]`` when
        ``vendor_ids`` is empty so the project response always carries a
        list (matches the monolith — no ``active`` field on the chip)."""
        if not vendor_ids:
            return []
        rows = self.db.execute(
            select(_VendorMirror.id, _VendorMirror.name)
            .where(_VendorMirror.id.in_(vendor_ids))
        ).all()
        # Preserve the order of vendor_ids so the response is deterministic.
        by_id = dict(rows)
        return [
            {"id": vid, "name": by_id.get(vid)}
            for vid in vendor_ids
        ]

    # --------------------------------------------------------------- CRUD

    def get(
        self, project_id: str, *, caller_is_admin: bool = True,
        caller_user_id: Optional[str] = None,
    ) -> ProjectResponse:
        """Single-project read.

        Doc-44 round 8 visibility hide: non-admin callers receive 404
        for projects in ``new`` or ``draft`` (mirrors the list-side
        silent-hide so FE can't distinguish "doesn't exist" from
        "not yet published"). See monolith
        PMIS-OpenProject/app/api/v3/projects/controller.py:304-319.

        2026-06-03 — this is the JIT entry point for the meeting
        milestone. If the project is published and has no meeting
        milestone yet, one is created lazily as part of the response
        shape so the returned ``meeting_milestone_id`` is always non-null
        for published projects with dates set.
        """
        row = self.service.get_by_id(project_id)
        if not caller_is_admin and (row.status or "") in ("new", "draft"):
            from app.core.errors import ProjectNotFoundError
            raise ProjectNotFoundError(
                f"Project with ID {project_id} not found"
            )
        # Only GET single hydrates attachments; matches monolith parity.
        return self._to_response(
            row,
            with_attachments=True,
            ensure_meeting_milestone=True,
            caller_user_id=caller_user_id,
        )

    def list_(
        self, *,
        offset: int = 1, page_size: int = 20,
        status: Optional[str] = None,
        active: Optional[bool] = None,
        public: Optional[bool] = None,
        include_deleted: bool = False,
        caller_user_id: Optional[str] = None,
        caller_is_admin: bool = False,
        caller_can_see_all: bool = False,
        caller_project_ids: Optional[set] = None,
    ) -> Dict[str, Any]:
        rows, total = self.service.list_(
            offset=offset, page_size=page_size,
            status=status, active=active, public=public,
            include_deleted=include_deleted,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
            caller_can_see_all=caller_can_see_all,
            caller_project_ids=caller_project_ids,
        )
        return {
            "items": [self._to_response(r, with_attachments=False) for r in rows],
            "total": total,
            "offset": offset,
            "page_size": page_size,
        }

    def create(
        self, payload: ProjectCreateRequest, *, caller_user_id: Optional[str],
    ) -> ProjectResponse:
        row = self.service.create(payload, caller_user_id=caller_user_id)
        return self._to_response(row)

    def upsert(
        self, project_id: str, payload: ProjectUpsertRequest,
        *, caller_user_id: Optional[str],
    ) -> Tuple[ProjectResponse, bool]:
        row, created = self.service.upsert(
            project_id, payload, caller_user_id=caller_user_id,
        )
        return self._to_response(row), created

    def update(
        self, project_id: str, payload: ProjectUpdateRequest,
        *, caller_user_id: Optional[str], request=None,
    ) -> ProjectResponse:
        row = self.service.update(
            project_id, payload,
            caller_user_id=caller_user_id, request=request,
        )
        return self._to_response(row)

    def delete(self, project_id: str, *, caller_user_id: Optional[str]) -> ProjectResponse:
        row = self.service.delete(project_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    # ------------------------------------------------------------ lifecycle

    def save(self, project_id: str, *, caller_user_id: Optional[str]) -> ProjectResponse:
        row = self.service.save(project_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def publish(self, project_id: str, *, caller_user_id: Optional[str]) -> ProjectResponse:
        row = self.service.publish(project_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    def close(
        self, project_id: str, payload: Optional[ProjectCloseRequest],
        *, caller_user_id: Optional[str],
    ) -> ProjectResponse:
        row = self.service.close(project_id, payload, caller_user_id=caller_user_id)
        return self._to_response(row)

    def reopen(self, project_id: str, *, caller_user_id: Optional[str]) -> ProjectResponse:
        row = self.service.reopen(project_id, caller_user_id=caller_user_id)
        return self._to_response(row)

    # ---------------------------------------------------- sub-route reads

    def audit_logs(
        self, project_id: str, *, offset: int = 1, page_size: int = 50,
    ) -> Dict[str, Any]:
        return self.audit_log_svc.list_for_project(
            project_id, offset=offset, page_size=page_size,
        )

    def discussion_feed(
        self, project_id: str, *, offset: int = 1, page_size: int = 50,
    ) -> Dict[str, Any]:
        return self.discussion.list_for_project(
            project_id, offset=offset, page_size=page_size,
        )

    def role_assignments(self, project_id: str) -> Dict[str, Any]:
        return self.assignable.list_role_assignments_for_project(project_id)

    def assignable_users(
        self, project_id: str, *, authorization: str = "",
    ) -> Dict[str, Any]:
        return self.assignable.list_assignable_users_for_project(
            project_id, authorization=authorization,
        )

    def list_attachments(self, project_id: str) -> Dict[str, Any]:
        return self.attachments.list_for_project(project_id)
