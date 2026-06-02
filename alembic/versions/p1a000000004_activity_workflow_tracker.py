"""Add activity_workflow_tracker table.

Revision ID: p1a000000004
Revises: p1a000000003
Create Date: 2026-05-28

Why:
  The activity-approval workflow runs in a separate Java microservice
  (DIGIT-style ``/_transition`` + per-businessId ``/_search``). Java owns
  the state machine; PMIS owns the activity and the routing metadata
  (consent divisions / owner division / vendor).

  Java's ``_search`` is per-businessId — it does NOT list activities
  pending for a given role. To power the Approval Inbox list (concerned
  division + activity owner views) without N round-trips to Java, PMIS
  tracks every activity that has entered the workflow in this table.

  Rows are inserted when SUBMIT is proxied to Java, updated on every
  transition, and queried role-aware for the inbox listing. The actual
  state on Java is the source of truth; ``current_state`` here is a
  cache (re-synced on read when stale).

Columns:
  business_id          activity UUID (matches Java's ``businessId``)
  process_instance_id  Java's process-instance id (latest known)
  current_state        Java state name (e.g. PENDINGATCONCERNEDDIVISION)
  consent_divisions    snapshot of activity.concerned_divisions at SUBMIT
  owner_division       snapshot of activity.owner_division at SUBMIT
  vendor_id            snapshot of activity.vendor_id at SUBMIT
  submitted_at         when the workflow was first kicked off
  last_synced_at       last time we re-fetched state from Java
  soft-delete columns  per PMIS convention
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "p1a000000004"
down_revision: str = "p1a000000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_workflow_tracker",
        sa.Column("business_id", sa.String(36), primary_key=True),
        sa.Column("activity_id", sa.String(36), sa.ForeignKey("project.activities.id"), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("process_instance_id", sa.String(64), nullable=True),
        sa.Column("current_state", sa.String(64), nullable=False),
        sa.Column("consent_divisions", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("owner_division", sa.String(64), nullable=True),
        sa.Column("vendor_id", sa.String(36), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("updated_by", sa.String(36)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.String(36)),
        schema="project",
    )
    op.create_index(
        "idx_activity_workflow_tracker_state_live",
        "activity_workflow_tracker", ["current_state", "deleted_at"],
        schema="project",
    )
    op.create_index(
        "idx_activity_workflow_tracker_owner_div",
        "activity_workflow_tracker", ["owner_division"],
        schema="project",
    )
    op.create_index(
        "idx_activity_workflow_tracker_project",
        "activity_workflow_tracker", ["project_id"],
        schema="project",
    )
    op.create_index(
        "idx_activity_workflow_tracker_activity",
        "activity_workflow_tracker", ["activity_id"],
        schema="project",
    )


def downgrade() -> None:
    op.drop_index("idx_activity_workflow_tracker_activity", table_name="activity_workflow_tracker", schema="project")
    op.drop_index("idx_activity_workflow_tracker_project", table_name="activity_workflow_tracker", schema="project")
    op.drop_index("idx_activity_workflow_tracker_owner_div", table_name="activity_workflow_tracker", schema="project")
    op.drop_index("idx_activity_workflow_tracker_state_live", table_name="activity_workflow_tracker", schema="project")
    op.drop_table("activity_workflow_tracker", schema="project")
