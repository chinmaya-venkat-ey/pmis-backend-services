"""MilestoneService — CRUD + position management + dependency cycle guard.

Inline-create contract: ``create`` writes the milestone row, optionally
followed (in the same DB transaction) by a comment row carrying inline
body and/or file attachments. The attachments list is the JSONB envelope
the route layer built from either the JSON request body or the multipart
files via the file client.
"""
from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.core.errors import (
    DependencyCycleError,
    MilestoneNotFoundError,
    ProjectNotFoundError,
    ValidationError,
)
from app.repositories.comment_repository import CommentRepository
from app.repositories.milestone_repository import MilestoneRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.milestone import MilestoneCreateRequest, MilestoneUpdateRequest
from app.utilities.catalogs import (
    active_milestone_statuses,
    active_priorities,
    is_known_milestone_status,
    is_known_priority,
    is_terminal_status,
)
from app.utilities.date_rules import validate_entity_dates
from app.utilities.project_lock import assert_milestone_activity_writable
from app.utilities.vendor_resolver import resolve_and_validate_vendor_ids


class MilestoneService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MilestoneRepository(db)
        self.projects = ProjectRepository(db)
        self.comments = CommentRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ------------------------------------------------------------------ read

    def get_by_id(self, milestone_id: str):
        row = self.repo.get_by_id(milestone_id)
        if row is None:
            raise MilestoneNotFoundError("The milestone could not be found.")
        return row

    def list_for_project(
        self, project_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ):
        return self.repo.list_for_project(
            project_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    # ------------------------------------------------------------------ write

    def create(
        self,
        project_id: str,
        payload: MilestoneCreateRequest,
        *,
        caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        # Project must be live and writable (monolith ``project_lock.py``).
        assert_milestone_activity_writable(project)
        # Project must have a start date — milestone dates floor against it.
        if project.start_date is None:
            raise ValidationError(
                "The project does not have a start date yet. Please set "
                "the project start date before adding milestones."
            )
        # Schema-level field_validator handles status (2-value hardcoded
        # set per monolith parity) and priority (uppercase normalize).
        # Service-level catalog checks are skipped — monolith uses the
        # same 2-value list, not the broader transitions catalog.
        self._validate_priority(payload.priority)
        # Vendor IDs: monolith parity — silently drop unknown / not-on-
        # project entries (don't raise). The resolved set is persisted on
        # the project_vendors mapping for the milestone but ``vendors`` on
        # the response stays empty (matches monolith milestone shape).
        canonical_vendor_ids = []
        if payload.vendor_ids:
            try:
                canonical_vendor_ids = resolve_and_validate_vendor_ids(
                    self.db, payload.vendor_ids,
                )
            except Exception:
                canonical_vendor_ids = []
        # Date rules — parent floor is the owning project (monolith parity).
        validate_entity_dates(
            entity_start=payload.start_date,
            entity_end=payload.end_date,
            actual_start=payload.actual_start_date,
            actual_end=payload.actual_end_date,
            parent_start_date=project.start_date,
            project_start_date=project.start_date,
            entity_label="milestone",
            parent_label="project",
        )
        position = (
            payload.position
            if payload.position is not None and payload.position > 0
            else self.repo.next_position_for_project(project_id)
        )
        row = self.repo.create(
            project_id=project_id,
            name=payload.name,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            actual_start_date=payload.actual_start_date,
            actual_end_date=payload.actual_end_date,
            status=payload.status or "not_completed",
            priority=payload.priority,
            position=position,
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        if payload.depends_on:
            self._guard_dependency_cycle(row.id, payload.depends_on)
            self._assert_deps_in_same_project(project_id, payload.depends_on)
            self._assert_dep_dates_outlasting(row, payload.depends_on)
            self.repo.replace_dependencies(row.id, payload.depends_on)
        if canonical_vendor_ids:
            self.repo.set_vendor_mapping(row.id, canonical_vendor_ids)

        # Inline comment / attachments — written under the new milestone.
        # Capture the created comment row on a transient ``_inline_comment``
        # attribute so the controller can echo it back on the multipart
        # create response (monolith parity — ``data.comment: {...}``).
        body_clean = (body or "").strip() or None
        atts = list(attachments or [])
        row._inline_comment = None
        if body_clean or atts:
            row._inline_comment = self.comments.create(
                target_kind="milestone",
                target_id=row.id,
                author_user_id=caller_user_id,
                body=body_clean,
                attachments=atts or None,
            )

        self.audit.write(
            project_id=project_id,
            target_kind="milestone", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"name": row.name, "position": row.position},
        )
        self.db.commit()
        return row

    def update(
        self,
        milestone_id: str,
        payload: MilestoneUpdateRequest,
        *, caller_user_id: Optional[str],
        request=None,
    ):
        row = self.get_by_id(milestone_id)
        updates = payload.model_dump(exclude_unset=True)
        depends_on = updates.pop("depends_on", None)
        vendor_ids = updates.pop("vendor_ids", None)
        if not updates and depends_on is None and vendor_ids is None:
            return row

        # ----- catalog + transition validations on touched fields ------
        # Status validation lives at the schema level (2-value hardcoded
        # set: not_completed / completed) — service-level catalog check
        # is skipped here to match monolith.
        if "priority" in updates:
            self._validate_priority(updates["priority"])
        # Status-completion + parent-revert gates fire when status changes.
        if "status" in updates and updates["status"] is not None:
            new_status = updates["status"]
            if is_terminal_status(new_status) and not is_terminal_status(row.status):
                # Completing — validate every child activity is complete.
                self._assert_all_child_activities_completed(row.id)
        # Vendor replacement: resolve + verify on-project.
        canonical_vendor_ids = None
        if vendor_ids is not None:
            canonical_vendor_ids = resolve_and_validate_vendor_ids(
                self.db, vendor_ids,
            )
            self._assert_vendors_on_project(row.project_id, canonical_vendor_ids)

        # Date-floor re-validation against the merged values. Apply the
        # same parent-floor + actual-date ordering rules the monolith
        # uses on PATCH.
        if (
            "start_date" in updates or "end_date" in updates
            or "actual_start_date" in updates or "actual_end_date" in updates
        ):
            project = self.projects.get_by_id(row.project_id)
            new_start = updates.get("start_date", row.start_date)
            new_end = updates.get("end_date", row.end_date)
            new_actual_start = updates.get(
                "actual_start_date", row.actual_start_date,
            )
            new_actual_end = updates.get(
                "actual_end_date", row.actual_end_date,
            )
            validate_entity_dates(
                entity_start=new_start,
                entity_end=new_end,
                actual_start=new_actual_start,
                actual_end=new_actual_end,
                parent_start_date=project.start_date if project else None,
                project_start_date=project.start_date if project else None,
                entity_label="milestone",
                parent_label="project",
            )
            # REVERSE Doc-31: this row's date move must not break any
            # downstream dependent's outlasting rule.
            self._assert_dep_dates_reverse(row, new_start, new_end)

        if request is not None and updates:
            from app.core.permissions import MILESTONE_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=MILESTONE_FIELD_CODES,
                touched_fields=set(updates.keys()),
                scope_key=("project", row.project_id),
            )

        if updates:
            before = {k: getattr(row, k) for k in updates}
            self.repo.update(row, updated_by=caller_user_id, **updates)
            self.audit.write(
                project_id=row.project_id,
                target_kind="milestone", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={
                    k: {"before": before[k], "after": updates[k]}
                    for k in updates
                },
            )
        if depends_on is not None:
            self._guard_dependency_cycle(row.id, depends_on)
            if depends_on:
                self._assert_deps_in_same_project(row.project_id, depends_on)
                self._assert_dep_dates_outlasting(row, depends_on)
            self.repo.replace_dependencies(row.id, depends_on)
            self.audit.write(
                project_id=row.project_id,
                target_kind="milestone", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={"depends_on": depends_on},
            )
        if canonical_vendor_ids is not None:
            self.repo.set_vendor_mapping(row.id, canonical_vendor_ids)
            self.audit.write(
                project_id=row.project_id,
                target_kind="milestone", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={"vendor_ids": canonical_vendor_ids},
            )

        self.db.commit()
        return row

    def delete(self, milestone_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(milestone_id)
        self.repo.soft_delete(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def restore(self, milestone_id: str, *, caller_user_id: Optional[str]):
        row = self.repo.get_by_id(milestone_id, include_deleted=True)
        if row is None:
            raise MilestoneNotFoundError("The milestone could not be found.")
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    # ----------------------------------------------------- dependency guard

    # ----------------------------------------------- catalog + gates -----

    def _validate_status(self, status: Optional[str]) -> None:
        if status is None:
            return
        if is_known_milestone_status(self.db, status):
            return
        allowed = active_milestone_statuses(self.db)
        raise ValidationError(
            f"Milestone status must be one of: {', '.join(allowed)}."
        )

    def _validate_priority(self, priority: Optional[str]) -> None:
        if priority is None:
            return
        if is_known_priority(self.db, priority):
            return
        allowed = active_priorities(self.db)
        raise ValidationError(
            f"Priority must be one of: {', '.join(allowed)}."
        )

    def _assert_vendors_on_project(
        self, project_id: str, vendor_ids: List[str],
    ) -> None:
        """Each milestone vendor must already be attached to the parent
        project (monolith parity — see
        ``PMIS-OpenProject/app/api/v3/milestones/services/create.py``
        and the project-vendor join enforced for activities)."""
        if not vendor_ids:
            return
        from sqlalchemy import select
        from app.models.project_vendor import ProjectVendor
        rows = self.db.execute(
            select(ProjectVendor.vendor_id)
            .where(ProjectVendor.project_id == project_id)
            .where(ProjectVendor.vendor_id.in_(vendor_ids))
        ).all()
        attached = {r[0] for r in rows}
        missing = [v for v in vendor_ids if v not in attached]
        if missing:
            raise ValidationError(
                f"Vendor(s) not attached to this project: "
                f"{', '.join(missing)}. Add them to the project first."
            )

    def _assert_deps_in_same_project(
        self, project_id: str, depends_on_ids: List[str],
    ) -> None:
        """Every dependency target must belong to the same project
        (monolith parity — depends-on across projects is rejected)."""
        if not depends_on_ids:
            return
        from sqlalchemy import select
        from app.models.milestone import Milestone
        rows = self.db.execute(
            select(Milestone.id)
            .where(Milestone.id.in_(depends_on_ids))
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
        ).all()
        found = {r[0] for r in rows}
        missing = [d for d in depends_on_ids if d not in found]
        if missing:
            raise ValidationError(
                f"Unknown or out-of-project milestone dependency "
                f"target(s): {', '.join(missing)}"
            )

    def _assert_dep_dates_outlasting(
        self, source_row, depends_on_ids: List[str],
    ) -> None:
        """Doc-31 outlasting: source.start >= every target.start AND
        source.end > every target.end (strict). Errors match monolith."""
        if not depends_on_ids:
            return
        from sqlalchemy import select
        from app.models.milestone import Milestone
        from app.utilities.dep_date_rules import (
            collect_forward_violations,
            raise_forward_if_violations,
        )
        rows = self.db.execute(
            select(Milestone.name, Milestone.start_date, Milestone.end_date)
            .where(Milestone.id.in_(depends_on_ids))
        ).all()
        targets = [(name, s, e) for name, s, e in rows]
        starts, ends = collect_forward_violations(
            source_start=source_row.start_date,
            source_end=source_row.end_date,
            targets=targets,
        )
        raise_forward_if_violations(
            starts, ends,
            source_label=f"'{source_row.name}'",
            source_start=source_row.start_date,
            source_end=source_row.end_date,
            kind_singular="milestone",
        )

    def _assert_dep_dates_reverse(
        self, target_row, new_start, new_end,
    ) -> None:
        """Doc-31 REVERSE: when this row's dates change, every milestone
        that depends ON it must still satisfy outlasting against the new
        target window."""
        from sqlalchemy import select
        from app.models.milestone import Milestone
        from app.models.milestone_dependency import MilestoneDependency
        from app.utilities.dep_date_rules import (
            collect_reverse_violations,
            raise_reverse_if_violations,
        )
        rows = self.db.execute(
            select(Milestone.name, Milestone.start_date, Milestone.end_date)
            .join(
                MilestoneDependency,
                MilestoneDependency.from_milestone_id == Milestone.id,
            )
            .where(MilestoneDependency.to_milestone_id == target_row.id)
            .where(Milestone.deleted_at.is_(None))
        ).all()
        if not rows:
            return
        sources = [(name, s, e) for name, s, e in rows]
        starts, ends = collect_reverse_violations(
            target_start=new_start,
            target_end=new_end,
            sources=sources,
        )
        raise_reverse_if_violations(
            starts, ends,
            target_label=f"Milestone '{target_row.name}'",
            target_start=new_start,
            target_end=new_end,
            kind_singular="milestone",
        )

    def _assert_all_child_activities_completed(
        self, milestone_id: str,
    ) -> None:
        """Children-completion gate (monolith parity): a milestone can
        only flip to completed when every live child activity is also
        completed. Error message matches monolith verbatim."""
        from sqlalchemy import select
        from app.models.activity import Activity
        rows = self.db.execute(
            select(Activity.name, Activity.status)
            .where(Activity.milestone_id == milestone_id)
            .where(Activity.deleted_at.is_(None))
        ).all()
        pending = [name for name, status in rows if not is_terminal_status(status)]
        if not pending:
            return
        names = ", ".join(pending[:5])
        more = f" and {len(pending) - 5} more" if len(pending) > 5 else ""
        plural = "ies are" if len(pending) > 1 else "y is"
        raise ValidationError(
            f"Cannot mark this milestone as completed — the following "
            f"child activit{plural} not yet completed: {names}{more}."
        )

    # ----------------------------------------------------- dep cycle -----

    def _guard_dependency_cycle(
        self, milestone_id: str, depends_on_ids: List[str],
    ) -> None:
        """Reject self-deps + any transitive cycle that closes back on
        ``milestone_id``. Monolith parity — raises ``ValidationError``
        (422) with the message format ``"Adding milestone dependency on
        <uuid> would create a cycle."``.
        """
        if milestone_id in depends_on_ids:
            raise ValidationError(
                f"Adding milestone dependency on {milestone_id} would "
                f"create a cycle."
            )
        visited: set[str] = set()
        frontier = list(depends_on_ids)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            if current == milestone_id:
                offender = depends_on_ids[0]
                raise ValidationError(
                    f"Adding milestone dependency on {offender} would "
                    f"create a cycle."
                )
            frontier.extend(self.repo.list_dependencies_for(current))
