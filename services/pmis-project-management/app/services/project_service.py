"""ProjectService — create / update / list / status-transition + vendor mapping
+ project audit log writes.

Status transitions consult `masters.project_status_transitions` (cross-schema).
If no edge matches (from_status, to_status, any role) the transition is rejected
with InvalidStatusTransitionError. Admins bypass the role check.

Vendor mapping: PUT /projects/{uuid}/vendors/replace replaces the M:N
project_vendors mapping wholesale.

Audit writes:
  - on create:    action='create',   target=(project, project.id)
  - on update:    action='update',   changes={k: {before, after}}
  - on delete:    action='delete'
  - on transition action='transition', changes={'from': X, 'to': Y, 'note': str}
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.errors import (
    InvalidStatusTransitionError,
    ProjectCodeConflictError,
    ProjectNotFoundError,
)
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_status_transition_repository import (
    ProjectStatusTransitionRepository,
)
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectStatusTransitionRequest,
    ProjectUpdateRequest,
)
from app.utilities.code_generators import generate_project_code


class ProjectService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectRepository(db)
        self.transitions = ProjectStatusTransitionRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ---------------------------------------------------------------- read

    def get_by_id(self, project_id: str):
        row = self.repo.get_by_id(project_id)
        if row is None:
            raise ProjectNotFoundError(f"Project {project_id!r} not found")
        return row

    def list_(
        self, *,
        offset: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        include_deleted: bool = False,
        caller_user_id: Optional[str] = None,
        caller_is_admin: bool = False,
    ) -> Tuple[List, int]:
        return self.repo.list_(
            offset=offset, page_size=page_size,
            status=status, include_deleted=include_deleted,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    # ---------------------------------------------------------------- write

    def create(
        self,
        payload: ProjectCreateRequest,
        *, caller_user_id: Optional[str],
    ):
        project_code = generate_project_code()
        # Defensive uniqueness check (the DB index also enforces).
        if self.repo.get_by_code(project_code) is not None:
            raise ProjectCodeConflictError(
                f"project_code {project_code!r} collided; retry create"
            )

        row = self.repo.create(
            project_code=project_code,
            name=payload.name,
            description=payload.description,
            public=payload.public,
            parent_id=payload.parent_id,
            owner=payload.owner,
            owner_other=payload.owner_other,
            category=payload.category,
            category_other=payload.category_other,
            category_other_reason=payload.category_other_reason,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        if payload.vendor_ids:
            self.repo.set_vendor_mapping(row.id, payload.vendor_ids)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"name": row.name, "project_code": row.project_code},
        )
        self.db.commit()
        return row

    def update(
        self,
        project_id: str,
        payload: ProjectUpdateRequest,
        *, caller_user_id: Optional[str],
        request=None,
    ):
        row = self.get_by_id(project_id)
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return row
        # Field-level RBAC (round-7): for non-admin callers, every touched
        # field must have its `projects:update:<field>` code held at
        # ("project", project_id) or globally.
        if request is not None:
            from app.core.permissions import PROJECT_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=PROJECT_FIELD_CODES,
                touched_fields=set(updates.keys()),
                scope_key=("project", project_id),
            )
        before = {k: getattr(row, k) for k in updates.keys()}
        self.repo.update(row, updated_by=caller_user_id, **updates)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="update", actor_user_id=caller_user_id,
            changes={k: {"before": before[k], "after": updates[k]} for k in updates},
        )
        self.db.commit()
        return row

    def delete(self, project_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(project_id)
        self.repo.soft_delete(row, deleted_by_user_id=caller_user_id)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def restore(self, project_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(project_id)
        self.repo.restore(row)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def set_vendors(self, project_id: str, vendor_ids: List[str], *, caller_user_id: Optional[str]):
        row = self.get_by_id(project_id)
        self.repo.set_vendor_mapping(row.id, vendor_ids)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="update", actor_user_id=caller_user_id,
            changes={"vendor_ids": vendor_ids},
        )
        self.db.commit()
        return row

    # ---------------------------------------------------------------- status transitions

    def transition_status(
        self,
        project_id: str,
        payload: ProjectStatusTransitionRequest,
        *,
        caller_user_id: Optional[str],
        caller_is_admin: bool,
        request=None,
    ):
        """Round-7: FSM gates by permission code.

        For the edge (from_status, to_status):
          - If no edge exists in masters.project_status_transitions OR it's
            inactive → 409 InvalidStatusTransitionError.
          - If the edge's permission_code is NULL → no special perm needed
            (universal edge — anyone authenticated with `projects:update:*`-ish
            authority can take it). We treat this as "always allowed".
          - Otherwise the caller must hold the edge's permission_code at
            ("project", project_id) or globally. Admins bypass.
        """
        row = self.get_by_id(project_id)
        from_status = row.status
        to_status = payload.to_status
        if from_status == to_status:
            return row

        edge = self.transitions.get_edge(from_status, to_status)
        if edge is None:
            raise InvalidStatusTransitionError(
                f"Transition {from_status!r} -> {to_status!r} is not defined in the FSM",
                details={"from_status": from_status, "to_status": to_status},
            )

        # Permission-code gate. None on the edge = universal (no extra perm).
        if edge.permission_code is not None and not caller_is_admin:
            scoped = (
                getattr(request.state, "scoped_permissions", None) or {}
            ) if request is not None else {}
            flat = (
                getattr(request.state, "user_permissions", None) or set()
            ) if request is not None else set()
            held_project = scoped.get(("project", project_id), set())
            held_global = scoped.get(("global", None), set())
            if (
                edge.permission_code not in held_project
                and edge.permission_code not in held_global
                and edge.permission_code not in flat
            ):
                raise InvalidStatusTransitionError(
                    f"Caller lacks {edge.permission_code!r} required for "
                    f"transition {from_status!r} -> {to_status!r}",
                    details={
                        "from_status": from_status,
                        "to_status": to_status,
                        "required_permission": edge.permission_code,
                    },
                )

        self.repo.update(row, status=to_status, updated_by=caller_user_id)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="transition", actor_user_id=caller_user_id,
            changes={"from": from_status, "to": to_status},
            note=payload.note,
        )
        self.db.commit()
        return row
