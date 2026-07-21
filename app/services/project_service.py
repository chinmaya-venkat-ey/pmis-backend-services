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
# Doc-finance: fields whose updates are publish-locked.
_FINANCE_LOCKED_FIELDS = (
    "total_project_value_excl_tax",
    "tax_percent",
    "ccn_cap_percent",
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
from app.utilities.required_fields import assert_required_not_cleared, is_empty_value
from app.utilities.vendor_resolver import resolve_and_validate_vendor_ids


class ProjectService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)
        # MilestoneRepository is used by :meth:`_ensure_meeting_milestone`
        # (2026-06-03 meeting-milestone feature). Importing here lets the
        # publish flow auto-create the hidden meeting container.
        from app.repositories.milestone_repository import MilestoneRepository
        self.milestones = MilestoneRepository(db)

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

    # --------------------------------------- project-specific config bag

    def get_config(self, project_id: str) -> dict:
        """Return the project's config/checks bag (``{}`` when unset)."""
        row = self.get_by_id(project_id)
        return dict(row.config or {})

    def set_config(
        self, project_id: str, patch: dict, *, caller_user_id: Optional[str],
    ) -> dict:
        """MERGE ``patch`` into the project's config bag and persist.

        Only the keys present in ``patch`` change; existing keys are preserved
        (partial-update / PATCH semantics), so adding a new check never wipes
        the others. Assigns a NEW dict so SQLAlchemy tracks the JSONB change.
        Returns the merged bag.
        """
        row = self.get_by_id(project_id)
        merged = {**(row.config or {}), **patch}
        self.repo.update(row, config=merged, updated_by=caller_user_id)
        self.audit.write(
            project_id=project_id, target_kind="project", target_id=project_id,
            action="update_config", actor_user_id=caller_user_id,
            changes={"config_keys": sorted(patch.keys())},
        )
        self.db.commit()
        return merged

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
        caller_can_see_all: bool = False,
        caller_project_ids: Optional[set] = None,
    ) -> Tuple[List, int]:
        return self.repo.list_(
            offset=offset, page_size=page_size,
            status=status, active=active, public=public,
            include_deleted=include_deleted,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
            caller_can_see_all=caller_can_see_all,
            caller_project_ids=caller_project_ids,
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
            require_owner=True,
        )
        # Required-field parity with the create UI: expected start/end dates
        # and at least one organization (vendor) are mandatory to create a
        # project. Update/PATCH stays partial and is not gated here.
        self._assert_project_create_required(payload)
        # Bug #141: project names must be unique among LIVE rows. Pre-check
        # surfaces a friendly 409; uq_projects_name_live is the race-safe
        # safety net.
        self._assert_name_unique(payload.name, exclude_id=None)
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

        create_kwargs = dict(
            project_code=project_code,
            name=payload.name,
            description=payload.description,
            # Doc-38: ``public`` removed from request wire — force False.
            public=False,
            status_explanation=payload.status_explanation,
            parent_id=payload.parent_id,
            status=payload.status or "new",
            owner=payload.owner,
            # Doc-38 ignore — see comment above.
            category=None,
            category_other=None,
            category_other_reason=None,
            start_date=payload.start_date,
            end_date=payload.end_date,
            # #321 / #322 — captured at creation (all optional/additive).
            contract_signing_date=getattr(payload, "contract_signing_date", None),
            actual_start_date=getattr(payload, "actual_start_date", None),
            actual_start_remarks=getattr(payload, "actual_start_remarks", None),
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        # Doc-finance: pass through any finance fields supplied on create.
        # Omitted fields fall back to the column server defaults (0 / 0 / 25).
        for fname in _FINANCE_LOCKED_FIELDS:
            value = getattr(payload, fname, None)
            if value is not None:
                create_kwargs[fname] = value
        row = self.repo.create(**create_kwargs)
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

    def _assert_project_create_required(self, payload) -> None:
        """Create-time mandatory-field gate mirroring the project UI:
        expected start date, expected end date and at least one organization
        (vendor) are required to create a project. Raises a single 422
        listing every missing field by wire name. Update/PATCH stays partial
        and is not gated here.
        """
        missing: list[str] = []
        if payload.start_date is None:
            missing.append("startDate")
        if payload.end_date is None:
            missing.append("endDate")
        if not payload.vendor_ids:
            missing.append("vendorIds")
        if missing:
            raise ValidationError(
                "Missing required field(s) for project creation: "
                f"{', '.join(missing)}.",
                details={"missing": missing},
            )

    def update(
        self,
        project_id: str,
        payload: ProjectUpdateRequest,
        *, caller_user_id: Optional[str],
        request=None,
    ):
        row = self.get_by_id(project_id)
        updates = payload.model_dump(exclude_unset=True)
        # Compute `touched` from the ORIGINAL payload before any pops so
        # the field walker can gate the sub-resource `vendor_ids` code.
        touched = set(updates.keys())
        vendor_ids = updates.pop("vendor_ids", None)
        if not updates and vendor_ids is None:
            return row

        # Required-field parity with create: a PATCH may omit these (no
        # change) but may not clear them to empty.
        assert_required_not_cleared(
            updates,
            {
                "name": "name", "owner": "owner",
                "start_date": "startDate", "end_date": "endDate",
            },
            entity="project",
        )
        # vendor_ids is popped out of ``updates`` above; reject an explicit
        # clear (sent as [] / null) while still allowing omission.
        if vendor_ids is not None and is_empty_value(vendor_ids):
            raise ValidationError(
                "Cannot clear required field(s) on project update: vendorIds.",
                details={"cleared": ["vendorIds"]},
            )

        # Doc-finance: publish-lock on the three contract finance fields.
        # If any are touched and the project is published, reject 409.
        # (The dedicated /finance PATCH route applies the same rule.)
        touched_finance = [f for f in _FINANCE_LOCKED_FIELDS if f in updates]
        if touched_finance and (row.status or "").lower() == "published":
            raise ConflictError(
                "Finance fields are locked once the project is published. "
                "Edits are not permitted after publish.",
                code="conflict",
                details={
                    "project_id": row.id,
                    "project_status": row.status,
                    "locked_fields": touched_finance,
                },
            )

        # ----- validations on touched fields (monolith parity) ----------
        if "status" in updates:
            self._validate_status(updates["status"])
        if "name" in updates and updates["name"] != row.name:
            # Bug #141: live names are unique. Skip the check when the
            # incoming name equals the stored one (no-op edits).
            self._assert_name_unique(updates["name"], exclude_id=row.id)
        if "owner" in updates:
            effective_owner = updates.get("owner", row.owner)
            validate_owner_pair(
                self.db,
                owner=effective_owner,
                require_owner=False,
            )
        if "parent_id" in updates:
            self._validate_parent_exists(updates["parent_id"], own_id=row.id)
        # Date-window guard: moving project dates inward of an existing
        # child's dates breaks the parent-floor invariant the FORWARD
        # date check enforces on child create. If any live milestone /
        # activity / task / subtask falls outside the merged new
        # window, reject the project update with a 422 listing the
        # offending children.
        if "start_date" in updates or "end_date" in updates:
            self._assert_dates_compatible_with_children(
                project_id=row.id,
                new_start=updates.get("start_date", row.start_date),
                new_end=updates.get("end_date", row.end_date),
            )
        # Resolve vendor tokens early so callers see a clean error before
        # the column updates commit.
        canonical_vendor_ids = None
        if vendor_ids is not None:
            canonical_vendor_ids = resolve_and_validate_vendor_ids(
                self.db, vendor_ids,
            )

        # Field-level RBAC for the column updates. `touched` was computed
        # from the original payload before sub-resource pops, so sub-resource
        # field codes (e.g. projects:update:vendors) are gated correctly.
        if request is not None and touched:
            from app.core.permissions import PROJECT_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=PROJECT_FIELD_CODES,
                touched_fields=touched,
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
            require_owner=True,
        )
        # Required-field parity with create — PUT is a full upsert, so the
        # required fields must be present and non-empty on BOTH the insert
        # and the in-place update branch.
        self._assert_project_create_required(payload)
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
        # Bug #141: enforce live-name uniqueness on both INSERT and UPDATE
        # branches. exclude_id keeps an in-place rename of the same row
        # from colliding with itself.
        self._assert_name_unique(
            payload.name,
            exclude_id=existing.id if existing is not None else None,
        )
        if existing is None:
            project_code = generate_project_code()
            if self.repo.get_by_code(project_code) is not None:
                raise ProjectCodeConflictError(
                    f"project_code {project_code!r} collided; retry upsert"
                )
            create_kwargs = dict(
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
                    # Doc-38 ignore.
                category=None,
                category_other=None,
                category_other_reason=None,
                start_date=payload.start_date,
                end_date=payload.end_date,
                created_by=caller_user_id,
                updated_by=caller_user_id,
            )
            # Doc-finance: pass-through finance fields on INSERT branch.
            # Omitted → column server defaults.
            for fname in _FINANCE_LOCKED_FIELDS:
                value = getattr(payload, fname, None)
                if value is not None:
                    create_kwargs[fname] = value
            row = self.repo.create(**create_kwargs)
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
            "category": None,
            "category_other": None,
            "category_other_reason": None,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
        }
        if payload.status is not None:
            fields["status"] = payload.status
        # Doc-finance: only update finance fields when explicitly sent
        # (not None). If they ARE sent and the project is published,
        # reject 409 (same publish-lock as PATCH).
        touched_finance: list[str] = []
        for fname in _FINANCE_LOCKED_FIELDS:
            value = getattr(payload, fname, None)
            if value is not None:
                fields[fname] = value
                touched_finance.append(fname)
        if touched_finance and (existing.status or "").lower() == "published":
            raise ConflictError(
                "Finance fields are locked once the project is published. "
                "Edits are not permitted after publish.",
                code="conflict",
                details={
                    "project_id": existing.id,
                    "project_status": existing.status,
                    "locked_fields": touched_finance,
                },
            )
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
        # Finance gate: every live milestone must be added on the Finance page
        # (bound to a Fixed cost row) before the project can be published.
        self._assert_milestones_in_finance(project_id)
        before = row.status
        self.repo.update(row, status="published", updated_by=caller_user_id)
        self.audit.write(
            project_id=row.id,
            target_kind="project", target_id=row.id,
            action="publish", actor_user_id=caller_user_id,
            changes={"from": before, "to": "published"},
        )
        # 2026-06-03: auto-create the hidden meeting milestone if absent.
        # See :meth:`_ensure_meeting_milestone` for the full lifecycle
        # description. Idempotent — a no-op when one already exists.
        self._ensure_meeting_milestone(row, caller_user_id=caller_user_id)
        self.db.commit()
        return row

    def _ensure_meeting_milestone(
        self, project, *, caller_user_id: Optional[str],
    ) -> Optional[str]:
        """Create the hidden meeting milestone for a project if it doesn't
        already exist. Returns the (possibly existing) meeting milestone's
        id, or None if the project has no dates set (date-rules require
        start/end on every milestone; we silently skip rather than fail).

        Called from:
          * :meth:`publish` — eagerly creates one as part of the publish
            transaction so a freshly-published project gets its container
            in the same commit.
          * Project-detail controller (JIT path) — fills the gap for
            projects published BEFORE this feature shipped.

        Idempotent: a partial unique index
        (``uq_milestones_one_meeting_per_project``) plus this look-before-
        leap check guarantee at most one live meeting milestone per
        project even under concurrent requests.

        The created milestone:
          * ``name = "Meetings"`` — placeholder, filtered out of UI anyway.
          * ``is_meeting = True``.
          * ``start_date`` / ``end_date`` = the project's own window so
            meeting activities can be scheduled anywhere inside it.
          * ``position`` = ``next_position_for_project`` so the unique
            (project_id, position) index doesn't conflict.
          * Status / category default to ``not_completed`` / ``original``.
        """
        existing = self.milestones.get_meeting_milestone_id(project.id)
        if existing is not None:
            return existing
        # Date-rules require start_date + end_date on every milestone row.
        # If the project doesn't have dates yet (rare — publishable projects
        # normally do), skip rather than fail and let the JIT-create retry
        # on a later detail fetch when dates exist.
        if not project.start_date or not project.end_date:
            return None
        position = self.milestones.next_position_for_project(project.id)
        new_row = self.milestones.create(
            project_id=project.id,
            name="Meetings",
            description=None,
            start_date=project.start_date,
            end_date=project.end_date,
            position=position,
            status="not_completed",
            priority=None,
            category="original",
            ccn_value=0,
            is_meeting=True,
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        return new_row.id

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

    def _assert_dates_compatible_with_children(
        self, *, project_id: str, new_start, new_end,
    ) -> None:
        """Bug #145: when project start/end dates move inward of any
        live milestone/activity/task/subtask's planned or actual dates,
        reject with a 422 listing up to 3 offenders.

          - new_start later than a child's start_date / actual_start_date
            → violation (child would now start before its parent project)
          - new_end earlier than a child's end_date / actual_end_date
            → violation (child would now end after its parent project)

        Inverse of the FORWARD ``validate_entity_dates`` check that runs
        on child create. Without this guard the user could move the
        project window inward and silently leave children dangling
        outside the parent's date range.

        All comparisons happen on the IST calendar date so naive vs.
        offset-aware datetimes compare cleanly (matches the project-wide
        convention in ``date_rules._to_ist_calendar_midnight``).
        """
        from datetime import date as _date
        from datetime import datetime as _datetime
        from app.models.activity import Activity
        from app.models.milestone import Milestone
        from app.models.subtask import Subtask
        from app.models.task import Task
        from app.utilities.date_rules import _to_ist_calendar_midnight

        def _norm(v):
            if v is None:
                return None
            if isinstance(v, _datetime):
                return _to_ist_calendar_midnight(v)
            if isinstance(v, _date):
                return _to_ist_calendar_midnight(
                    _datetime(v.year, v.month, v.day)
                )
            return v

        n_start = _norm(new_start)
        n_end = _norm(new_end)

        violations: List[str] = []

        def _scan(model, kind: str):
            rows = self.db.execute(
                select(
                    model.name,
                    model.start_date,
                    model.end_date,
                    model.actual_start_date,
                    model.actual_end_date,
                )
                .where(model.project_id == project_id)
                .where(model.deleted_at.is_(None))
            ).all()
            for name, start, end, a_start, a_end in rows:
                start_n = _norm(start)
                end_n = _norm(end)
                a_start_n = _norm(a_start)
                a_end_n = _norm(a_end)
                if n_start is not None:
                    if start_n is not None and start_n < n_start:
                        violations.append(
                            f"{kind} '{name}' starts {start_n.date()} "
                            f"(before new project start {n_start.date()})"
                        )
                    elif a_start_n is not None and a_start_n < n_start:
                        violations.append(
                            f"{kind} '{name}' actually started "
                            f"{a_start_n.date()} (before new project start)"
                        )
                if n_end is not None:
                    if end_n is not None and end_n > n_end:
                        violations.append(
                            f"{kind} '{name}' ends {end_n.date()} "
                            f"(after new project end {n_end.date()})"
                        )
                    elif a_end_n is not None and a_end_n > n_end:
                        violations.append(
                            f"{kind} '{name}' actually ended "
                            f"{a_end_n.date()} (after new project end)"
                        )

        _scan(Milestone, "Milestone")
        _scan(Activity, "Activity")
        _scan(Task, "Task")
        _scan(Subtask, "Subtask")

        if not violations:
            return

        listed = "; ".join(violations[:3])
        more = (
            f" (+{len(violations) - 3} more)"
            if len(violations) > 3 else ""
        )
        raise ValidationError(
            f"Cannot change project dates — the new window conflicts "
            f"with existing children: {listed}{more}.",
            details={
                "errorIdentifier": "project_dates_conflict_with_children",
                "violation_count": len(violations),
                "violations": violations[:10],
            },
        )

    def _assert_name_unique(
        self, name: Optional[str], *, exclude_id: Optional[str],
    ) -> None:
        """Bug #141: reject any project whose name collides with a live
        sibling. Soft-deleted rows don't block the name (matches the
        partial unique index uq_projects_name_live)."""
        if not name:
            return
        if self.repo.name_in_use(name, exclude_id=exclude_id):
            raise ConflictError(
                f"A project named {name!r} already exists. Project names "
                "must be unique.",
                code="project_name_conflict",
                details={"name": name},
            )

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

        Meeting milestones (``is_meeting=True``) are excluded — they're
        auto-created post-publish anyway, and would always be empty at
        the moment the gate fires. The auto-create in :meth:`publish`
        runs AFTER this gate, so in normal flow they wouldn't even exist
        here, but the filter is defensive in case a meeting milestone
        was ever inserted manually or via a future code path.
        """
        live_milestones = self.db.execute(
            select(Milestone.id, Milestone.name)
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
            .where(Milestone.is_meeting.is_(False))
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

    def _assert_milestones_in_finance(self, project_id: str) -> None:
        """Finance publishability gate — every live (non-meeting) milestone must
        be added on the Finance page, i.e. bound to a LIVE FIXED cost row (which
        is what gives the milestone its payment term). A milestone left out of
        all cost rows blocks publish. Same ``invalid_publish`` envelope as
        :meth:`_assert_publishable`; errorIdentifier ``milestone_not_in_finance``.

        Meeting milestones (``is_meeting=True``) are excluded — they're
        auto-created post-publish and never appear on the Finance page.
        """
        from app.models.cost_item_milestone import CostItemMilestone
        from app.models.project_cost_item import ProjectCostItem

        live_milestones = self.db.execute(
            select(Milestone.id, Milestone.name)
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
            .where(Milestone.is_meeting.is_(False))
        ).all()
        if not live_milestones:
            # No milestones at all is already rejected by _assert_publishable.
            return

        bound_ids = {
            r[0] for r in self.db.execute(
                select(CostItemMilestone.milestone_id)
                .join(ProjectCostItem, ProjectCostItem.id == CostItemMilestone.cost_item_id)
                .where(ProjectCostItem.project_id == project_id)
                .where(ProjectCostItem.deleted_at.is_(None))
                .where(ProjectCostItem.cost_type_code != "one_time")
                .distinct()
            ).all()
        }
        missing = [(mid, name) for mid, name in live_milestones if mid not in bound_ids]
        if missing:
            # Monolith parity: each name is wrapped in single quotes.
            names = ", ".join(f"'{name}'" for _mid, name in missing)
            raise ValidationError(
                f"Cannot publish: the following milestone(s) are not added on "
                f"the Finance page: {names}. Add each milestone to a cost row in "
                f"Finance before publishing.",
                code="invalid_publish",
                details={
                    "errorIdentifier": "milestone_not_in_finance",
                    "milestoneIds": [mid for mid, _ in missing],
                    "milestoneNames": [name for _mid, name in missing],
                },
            )
