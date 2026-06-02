"""ActivityWorkflowTrackerRepository — CRUD + role-aware listing.

SQL only. Business rules live in
``services/approval_inbox_service.py``.

The role-aware listing methods take the caller's division code and the
state name they're interested in; they NEVER decide which role applies
or what the state name should be — that's the service's job.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.activity_workflow_tracker import ActivityWorkflowTracker


class ActivityWorkflowTrackerRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── single-row reads ─────────────────────────────────────────────────

    def get(self, business_id: str) -> Optional[ActivityWorkflowTracker]:
        row = self.db.get(ActivityWorkflowTracker, business_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    # ── inbox listing ────────────────────────────────────────────────────

    def list_for_concerned_division(
        self,
        *,
        division_code: str,
        states: Iterable[str],
    ) -> List[ActivityWorkflowTracker]:
        """All live tracker rows whose ``consent_divisions`` JSONB array
        contains ``division_code`` AND whose ``current_state`` is in the
        given set. The state-set is supplied by the service so this repo
        stays decoupled from the Java state vocabulary."""
        stmt = (
            select(ActivityWorkflowTracker)
            .where(ActivityWorkflowTracker.deleted_at.is_(None))
            .where(ActivityWorkflowTracker.current_state.in_(list(states)))
            .where(ActivityWorkflowTracker.consent_divisions.contains([division_code]))
            .order_by(ActivityWorkflowTracker.submitted_at.desc().nullslast())
        )
        return list(self.db.execute(stmt).scalars())

    def list_for_owner_division(
        self,
        *,
        division_code: str,
        states: Iterable[str],
    ) -> List[ActivityWorkflowTracker]:
        """All live tracker rows whose ``owner_division`` equals the given
        code AND whose ``current_state`` is in the given set."""
        stmt = (
            select(ActivityWorkflowTracker)
            .where(ActivityWorkflowTracker.deleted_at.is_(None))
            .where(ActivityWorkflowTracker.current_state.in_(list(states)))
            .where(ActivityWorkflowTracker.owner_division == division_code)
            .order_by(ActivityWorkflowTracker.submitted_at.desc().nullslast())
        )
        return list(self.db.execute(stmt).scalars())

    def list_all_live(
        self,
        *,
        states: Optional[Iterable[str]] = None,
    ) -> List[ActivityWorkflowTracker]:
        """Admin view — no role-filter."""
        stmt = (
            select(ActivityWorkflowTracker)
            .where(ActivityWorkflowTracker.deleted_at.is_(None))
        )
        if states:
            stmt = stmt.where(ActivityWorkflowTracker.current_state.in_(list(states)))
        stmt = stmt.order_by(ActivityWorkflowTracker.submitted_at.desc().nullslast())
        return list(self.db.execute(stmt).scalars())

    # ── writes (used by the transition proxy once we wire it) ────────────

    def upsert_on_submit(
        self,
        *,
        business_id: str,
        activity_id: str,
        project_id: str,
        process_instance_id: Optional[str],
        current_state: str,
        consent_divisions: List[str],
        owner_division: Optional[str],
        vendor_id: Optional[str],
        actor_user_id: Optional[str],
    ) -> ActivityWorkflowTracker:
        """Idempotent for the SUBMIT path — used by the (future) transition
        proxy. Snapshots routing metadata from the activity so the inbox
        query doesn't drift if the activity is later edited.
        """
        now = datetime.utcnow()
        row = self.db.get(ActivityWorkflowTracker, business_id)
        if row is None:
            row = ActivityWorkflowTracker(
                business_id=business_id,
                activity_id=activity_id,
                project_id=project_id,
                process_instance_id=process_instance_id,
                current_state=current_state,
                consent_divisions=list(consent_divisions or []),
                owner_division=owner_division,
                vendor_id=vendor_id,
                submitted_at=now,
                last_synced_at=now,
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
            self.db.add(row)
        else:
            row.process_instance_id = process_instance_id or row.process_instance_id
            row.current_state = current_state
            row.consent_divisions = list(consent_divisions or [])
            row.owner_division = owner_division
            row.vendor_id = vendor_id
            row.last_synced_at = now
            row.updated_by = actor_user_id
            # Note: don't overwrite submitted_at — it captures the FIRST submit.
            row.deleted_at = None
            row.deleted_by = None
        self.db.flush()
        return row

    def update_state(
        self,
        row: ActivityWorkflowTracker,
        *,
        current_state: str,
        process_instance_id: Optional[str] = None,
        actor_user_id: Optional[str] = None,
    ) -> ActivityWorkflowTracker:
        """Used by transition proxy after a non-SUBMIT action and by the
        inbox detail handler when re-syncing from Java's ``_search``."""
        row.current_state = current_state
        if process_instance_id:
            row.process_instance_id = process_instance_id
        row.last_synced_at = datetime.utcnow()
        if actor_user_id:
            row.updated_by = actor_user_id
        self.db.flush()
        return row
