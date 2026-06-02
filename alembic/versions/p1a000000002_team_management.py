"""Team management tables: project_ownership + activity_assignments.

Revision ID: p1a000000002
Revises: p1a000000001
Create Date: 2026-05-24

Why:
  The Manage-Team page (UI) requires:
    1. project_ownership  — who is the Project Owner and Approver for a project
                           (distinct from the org-tier project_admin role stored
                            in users.user_role_assignments).
    2. activity_assignments — per-activity user assignments:
         owner, owner_approver, division_user, division_approver.
       division_code is NULL for activity-level roles and set to a
       masters.divisions.code value for division-specific roles.

  Both tables live in the `project` schema and use logical FKs only
  (no cross-schema FK constraints — same convention as the rest of
  the project schema).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000002"
down_revision: str = "p1a000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── project_ownership ─────────────────────────────────────────────────
    op.create_table(
        "project_ownership",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.projects.id"), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role IN ('project_owner', 'approver')", name="ck_project_ownership_role"),
        sa.UniqueConstraint("project_id", "user_id", "role", name="uq_project_ownership_project_user_role"),
        schema="project",
    )
    op.create_index("idx_project_ownership_project", "project_ownership", ["project_id"], schema="project")
    op.create_index("idx_project_ownership_user", "project_ownership", ["user_id"], schema="project")

    # ── activity_assignments ───────────────────────────────────────────────
    op.create_table(
        "activity_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), sa.ForeignKey("project.activities.id"), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("division_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "role IN ('owner', 'owner_approver', 'division_user', 'division_approver')",
            name="ck_activity_assignments_role",
        ),
        sa.UniqueConstraint(
            "activity_id", "user_id", "role", "division_code",
            name="uq_activity_assignments_activity_user_role_div",
        ),
        schema="project",
    )
    op.create_index("idx_activity_assignments_activity", "activity_assignments", ["activity_id"], schema="project")
    op.create_index("idx_activity_assignments_project", "activity_assignments", ["project_id"], schema="project")
    op.create_index("idx_activity_assignments_user", "activity_assignments", ["user_id"], schema="project")


def downgrade() -> None:
    op.drop_table("activity_assignments", schema="project")
    op.drop_table("project_ownership", schema="project")
