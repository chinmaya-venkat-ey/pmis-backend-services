"""ProjectService — project CRUD, upsert, lifecycle (save / publish / close),
vendor mapping, restore, plus project-scoped reads used by the audit-log,
discussion-feed, and attachment-list endpoints.

Status transitions match the monolith's verb-based contract:
  - ``save``    : ``new -> draft`` once at least one live milestone exists.
                  No-op when status is already past ``new``.
  - ``publish`` : ``draft -> published`` (admins / projects:publish holders).
  - ``close``   : ``* -> closed``       (projects:close holders; optional
                  ``reason`` saved on the audit note).

Audit events:
  - create   action='create'    target=(project, project.id)
  - update   action='update'    changes={k: {before, after}}
  - upsert   action='create' OR 'update' as above
  - delete   action='delete'
  - restore  action='restore'
  - save     action='save'      changes={'from': 'new', 'to': 'draft'}
  - publish  action='publish'   changes={'from': ..., 'to': 'published'}
  - close    action='close'     changes={'from': ..., 'to': 'closed'}, note=reason
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    ConflictError,
    NotFoundError,
    ProjectCodeConflictError,
    ProjectNotFoundError,
    ValidationError,
)
from app.models.activity import Activity
from app.models.milestone import Milestone
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import (
    ProjectCloseRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectUpsertRequest,
)
from app.utilities.catalogs import (
    active_project_statuses,
    is_known_project_status,
)
from app.utilities.code_generators import generate_project_code
from app.utilities.owner_pair import validate_owner_pair
from app.utilities.vendor_resolver import resolve_and_validate_vendor_ids


class ProjectService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ---------------------------------------------------------------- read

    def get_by_id(self, project_id: str):
        row = self.repo.get_by_id(project_id)
        if row is None:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        return row

    def get_by_id_include_deleted(self, project_id: str):
        row = self.repo.get_by_id(project_id, include_deleted=True)
        if row is None:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        return row

    def list_(
        self, *,
        offset: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        active: Optional[bool] = None,
        public: Optional[bool] = None,
        include_deleted: bool = False,
        caller_user_id: Optional[str] = None,
        caller_is_admin: bool = False,
    ) -> Tuple[List, int]:
        return self.repo.list_(
            offset=offset, page_size=page_size,
            status=status, active=active, public=public,
            include_deleted=include_deleted,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    # ---------------------------------------------------------------- write

    def create(
        self,
        payload: ProjectCreateRequest,
        *, caller_user_id: Optional[str],
    ):
        # ----- pre-insert validations (monolith parity) ------------------
        # Status is validated at the schema level (4-value fallback) per
        # monolith parity — no service-level status check on CREATE.
        validate_owner_pair(
            self.db,
            owner=payload.owner,
            owner_other=payload.owner_other,
            require_owner=True,
        )
        # Doc-38: category / categoryOther / categoryOtherReason were
        # removed from the request wire in the monolith. The schema still
        # accepts them for legacy callers, but the controller / service
        # force-NULL them so the stored row + response match monolith.
        self._validate_parent_exists(payload.parent_id)
        canonical_vendor_ids = resolve_and_validate_vendor_ids(
            self.db, payload.vendor_ids or [],
        )

        project_code = generate_project_code()
        if self.repo.get_by_code(project_code) is not None:
            raise ProjectCodeConflictError(
                f"project_code {project_code!r} collided; retry create"
            )

        row = self.repo.create(
            project_code=project_code,
            name=payload.name,
            description=payload.description,
            # Doc-38: ``public`` removed from request wire — force False.
            public=False,
            status_explanation=payload.status_explanation,
            parent_id=payload.parent_id,
            status=payload.status or "new",
            owner=payload.owner,
            owner_other=payload.owner_other,
            # Doc-38 ignore — see comment above.
            category=None,
            category_other=None,
            category_other_reason=None,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        if canonical_vendor_ids:
            self.repo.set_vendor_mapping(row.id, canonical_vendor_ids)
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
        vendor_ids = updates.pop("vendor_ids", None)
        if not updates and vendor_ids is None:
            return row

        # ----- validations on touched fields (monolith parity) ----------
        if "status" in updates:
            self._validate_status(updates["status"])
        if "owner" in updates or "owner_other" in updates:
            effective_owner = updates.get("owner", row.owner)
            effective_other = updates.get("owner_other", row.owner_other)
            validate_owner_pair(
                self.db,
                owner=effective_owner,
                owner_other=effective_other,
                require_owner=False,
            )
        if "parent_id" in updates:
            self._validate_parent_exists(updates["parent_id"], own_id=row.id)
        # Resolve vendor tokens early so callers see a clean error before
        # the column updates commit.
        canonical_vendor_ids = None
        if vendor_ids is not None:
            canonical_vendor_ids = resolve_and_validate_vendor_ids(
                self.db, vendor_ids,
            )

        # Field-level RBAC for the column updates.
        if request is not None and updates:
            from app.core.permissions import PROJECT_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=PROJECT_FIELD_CODES,
                touched_fields=set(updates.keys()),
                scope_key=("project", project_id),
            )

        if updates:
            before = {k: getattr(row, k) for k in updates.keys()}
            self.repo.update(row, updated_by=caller_user_id, **updates)
            self.audit.write(
                project_id=row.id,
                target_kind="project", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={
                    k: {"before": before[k], "after": updates[k]}
                    for k in updates
                },
            )

        if canonical_vendor_ids is not None:
            self.repo.set_vendor_mapping(row.id, canonical_vendor_ids)
            self.audit.write(
                project_id=row.id,
                target_kind="project", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={"vendor_ids": canonical_vendor_ids},
            )

        self.db.commit()
        return row

    def upsert(
        self,
        project_id: str,
        payload: ProjectUpsertRequest,
        *, caller_user_id: Optional[str],
    ) -> Tuple[Any, bool]:
        """Idempotent create-or-update keyed by ``project_id``.

        Returns ``(row, created)`` — ``created`` is True on the INSERT
        branch, False on the UPDATE branch. The route layer maps these
        to HTTP 201 vs 200.
        """
        # ----- pre-write validations (apply on both INSERT and UPDATE) --
        self._validate_status(payload.status)
        validate_owner_pair(
            self.db,
            owner=payload.owner,
            owner_other=payload.owner_other,
            require_owner=True,
        )
        # Doc-38 ignore: category fields force-NULL (see create()).
        self._validate_parent_exists(payload.parent_id, own_id=project_id)
        canonical_vendor_ids = (
            resolve_and_validate_vendor_ids(self.db, payload.vendor_ids)
            if payload.vendor_ids is not None else None
        )

        # Monolith parity: a soft-deleted UUID is treated as EXISTING for
        # upsert (the row is updated in-place; ``deleted_at`` /
        # ``deleted_by`` are NOT cleared). PUT returns 200 with
        # ``_created: false`` and the response carries the original
        # delete metadata. This mirrors monolith's "PUT updates the
        # zombie row in place" semantics — to bring it back to live the
        # caller must use the dedicated /restore endpoint.
        existing = self.repo.get_by_id(project_id, include_deleted=True)
        if existing is None:
            project_code = generate_project_code()
            if self.repo.get_by_code(project_code) is not None:
                raise ProjectCodeConflictError(
                    f"project_code {project_code!r} collided; retry upsert"
                )
            row = self.repo.create(
                id=project_id,
                project_code=project_code,
                name=payload.name,
                description=payload.description,
                # Doc-38: ``public`` removed from request wire.
                public=False,
                status_explanation=payload.status_explanation,
                parent_id=payload.parent_id,
                status=payload.status or "new",
                owner=payload.owner,
                owner_other=payload.owner_other,
                # Doc-38 ignore.
                category=None,
                category_other=None,
                category_other_reason=None,
                start_date=payload.start_date,
                end_date=payload.end_date,
                created_by=caller_user_id,
                updated_by=caller_user_id,
            )
            if canonical_vendor_ids is not None:
                self.repo.set_vendor_mapping(row.id, canonical_vendor_ids)
            self.audit.write(
                project_id=row.id,
                target_kind="project", target_id=row.id,
                action="create", actor_user_id=caller_user_id,
                changes={"name": row.name, "project_code": row.project_code},
            )
            self.db.commit()
            return row, True

        # Update branch — preserve project_code. Doc-38: category fields
        # force-NULL on every upsert call (matches monolith controller).
        fields = {
            "name": payload.name,
            "description": payload.description,
            # Doc-38: ``public`` removed from upsert request wire.
            "public": False,
            "status_explanation": payload.status_explanation,
            "parent_id": payload.parent_id,
            "owner": payload.owner,
            "owner_other": payload.owner_other,
            "category": None,
            "category_other": None,
            "category_other_reason": None,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
        }
        if payload.status is not None:
            fields["status"] = payload.status
        before = {k: getattr(existing, k) for k in fields.keys()}
        self.repo.update(existing, updated_by=caller_user_id, **fields)
        if canonical_vendor_ids is not None:
            self.repo.set_vendor_mapping(existing.id, canonical_vendor_ids)
        self.audit.write(
            project_id=existing.id,
            target_kind="project", target_id=existing.id,
            action="update", actor_user_id=caller_user_id,
            changes={
                k: {"before": before[k], "after": fields[k]} for k in fields
            },
        )
        self.db.commit()
        return existing, False

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

    # ---------------------------------------------------------- lifecycle

    def save(self, project_id: str, *, caller_user_id: Optional[str]):
        """``new -> draft`` once at least one live milestone exists.
        Idempotent: a no-op once past ``new``. Matches monolith's
        ``POST /projects/{id}/save``.

        Missing-milestone is a 422 ``ValidationError`` (matches the
        monolith's ``validation_error`` mapping — see
        PMIS-OpenProject/tests/test_projects.py:107-113 which asserts
        ``resp.status_code == 422``).
        """
        row = self.get_by_id(project_id)
        if row.status != "new":
            return row
        live_count = self.db.execute(
            select(func.count()).select_from(Milestone)
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
        ).scalar_one()
        if live_count <= 0:
            # Monolith parity: generic ``validation_error`` identifier
            # with the canonical save message.
            raise ValidationError(
                "Add at least one milestone before saving the project."
            )
        before = row.status
        self.repo.update(row, status="draft", updated_by=caller_user_id)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="save", actor_user_id=caller_user_id,
            changes={"from": before, "to": "draft"},
        )
        self.db.commit()
        return row

    def publish(self, project_id: str, *, caller_user_id: Optional[str]):
        """Flip status to ``published``. Re-publishing an already-published
        project raises 409 ``ConflictError`` (matches the monolith's
        ``invalid_transition`` error and the test at
        PMIS-OpenProject/tests/test_projects.py:150-155 which asserts a
        second publish returns 409).

        Doc-27 structural-completeness gate also applies: every live
        milestone must have at least one live activity. Errors here
        match the monolith's ``invalid_publish`` shape verbatim.
        """
        row = self.get_by_id(project_id)
        if row.status == "published":
            raise ConflictError(
                "Project is already published.",
                code="invalid_transition",
                details={"from_status": row.status, "to_status": "published"},
            )
        if row.status == "closed":
            raise ConflictError(
                "Cannot publish a closed project.",
                code="invalid_transition",
                details={"from_status": row.status, "to_status": "published"},
            )
        # Doc-27 publishability gate.
        self._assert_publishable(project_id)
        before = row.status
        self.repo.update(row, status="published", updated_by=caller_user_id)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="publish", actor_user_id=caller_user_id,
            changes={"from": before, "to": "published"},
        )
        self.db.commit()
        return row

    def close(
        self,
        project_id: str,
        payload: Optional[ProjectCloseRequest],
        *, caller_user_id: Optional[str],
    ):
        row = self.get_by_id(project_id)
        if row.status == "closed":
            return row
        before = row.status
        reason = payload.reason if payload is not None else None
        # Monolith parity: the optional ``reason`` body is persisted onto
        # ``statusExplanation`` so the closed-project response carries it.
        update_kwargs = {"status": "closed", "updated_by": caller_user_id}
        if reason is not None:
            update_kwargs["status_explanation"] = reason
        self.repo.update(row, **update_kwargs)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="close", actor_user_id=caller_user_id,
            changes={"from": before, "to": "closed"},
            note=reason,
        )
        self.db.commit()
        return row

    def reopen(self, project_id: str, *, caller_user_id: Optional[str]):
        """``closed -> published``. Inverse of ``close``. Refuses if the
        project is not currently closed (no-op semantics would be more
        forgiving but a 409 here surfaces stale FE state).

        Clears ``status_explanation`` unconditionally so a stale
        auto-complete marker or manual close reason doesn't linger after
        the reopen. The audit row captures the prior reason in ``note``
        for traceability.
        """
        row = self.get_by_id(project_id)
        if row.status != "closed":
            raise ConflictError(
                "Project is not closed.",
                code="invalid_transition",
                details={"from_status": row.status, "to_status": "published"},
            )
        before = row.status
        prior_reason = (row.status_explanation or "").strip() or None
        self.repo.update(
            row,
            status="published",
            status_explanation=None,
            updated_by=caller_user_id,
        )
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="reopen", actor_user_id=caller_user_id,
            changes={"from": before, "to": "published"},
            note=prior_reason,
        )
        self.db.commit()
        return row

    # ------------------------------------------------------------ helpers

    def _validate_status(self, status: Optional[str]) -> None:
        """Reject statuses outside the catalog / fallback set.

        Error message matches monolith
        (``app/api/v3/projects/services/create.py:79-86``):
            ``"Invalid status '{status}'. Allowed: {comma-separated}."``
        """
        if status is None:
            return
        if is_known_project_status(self.db, status):
            return
        allowed = active_project_statuses(self.db)
        # Monolith format (no trailing period — matches
        # PMIS-OpenProject/app/api/v3/projects/services/create.py:84).
        raise ValidationError(
            f"Invalid status '{status}'. Allowed: {', '.join(allowed)}"
        )

    def _validate_parent_exists(
        self, parent_id: Optional[str], *, own_id: Optional[str] = None,
    ) -> None:
        """``parent_id`` (when supplied) must point at a live project.

        Error message matches monolith
        (``app/api/v3/projects/services/create.py:174-178``):
            ``"Parent project with ID {parent_id} does not exist"``

        ``own_id`` (the row being upserted) is rejected as self-parent —
        prevents the simplest cycle. Deeper cycle detection is NOT
        enforced here (monolith doesn't either, per the audit).
        """
        if parent_id is None or not str(parent_id).strip():
            return
        if own_id is not None and parent_id == own_id:
            raise NotFoundError(
                f"Parent project with ID {parent_id} does not exist"
            )
        parent = self.repo.get_by_id(parent_id)
        if parent is None:
            raise NotFoundError(
                f"Parent project with ID {parent_id} does not exist"
            )

    def _assert_publishable(self, project_id: str) -> None:
        """Doc-27 publishability gate — every live milestone must have
        ≥1 live activity. Errors match monolith
        (``publish.py:97-121``) byte-for-byte.
        """
        live_milestones = self.db.execute(
            select(Milestone.id, Milestone.name)
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
        ).all()
        if not live_milestones:
            # Monolith pattern: top-level identifier is ``invalid_publish``;
            # the specific sub-code rides in _embedded.details.
            raise ValidationError(
                "Cannot publish: the project has no milestones. Add at "
                "least one milestone with one activity before publishing.",
                code="invalid_publish",
                details={"errorIdentifier": "no_milestones"},
            )
        # Per-milestone activity coverage check.
        milestone_ids = [mid for mid, _ in live_milestones]
        rows = self.db.execute(
            select(Activity.milestone_id)
            .where(Activity.milestone_id.in_(milestone_ids))
            .where(Activity.deleted_at.is_(None))
            .distinct()
        ).all()
        covered_ids = {r[0] for r in rows}
        missing = [
            (mid, name) for mid, name in live_milestones
            if mid not in covered_ids
        ]
        if missing:
            # Monolith parity: each name is wrapped in single quotes.
            names = ", ".join(f"'{name}'" for _mid, name in missing)
            raise ValidationError(
                f"Cannot publish: the following milestone(s) have no "
                f"activities: {names}. Add at least one activity to each, "
                f"or delete the empty milestone.",
                code="invalid_publish",
                details={
                    "errorIdentifier": "milestone_without_activity",
                    "milestoneIds": [mid for mid, _ in missing],
                    "milestoneNames": [name for _mid, name in missing],
                },
            )
