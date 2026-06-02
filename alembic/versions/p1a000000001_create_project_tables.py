"""Initial schema for pmis-project-management — creates 16 owned tables
under the `project` Postgres schema.

Tables:
  projects, project_vendors, project_audit_logs,
  milestones, milestone_dependencies, milestone_vendors,
  activities, activity_dependencies, activity_resources,
  tasks, task_dependencies, task_resources,
  subtasks, subtask_dependencies, subtask_resources,
  comments

NO cross-schema FK constraints. user-id refs (created_by / updated_by / deleted_by
/ author_user_id / assigned_to / actor_user_id) are logical FKs to users.users.id.
vendor_id columns are logical FKs to masters.vendors.id. priority is logical FK
to masters.priorities.code; status logical FK to masters.activity_statuses.code
or masters.milestone_statuses.code per column.

Partial unique indexes (where deleted_at IS NULL) drive the display-label rank:
  M{n}, A{m}.{a}, T{m}.{a}.{t}, S{m}.{a}.{t}.{s1}[.{sN}]

Revision ID: p1a000000001
Revises: None
Create Date: 2026-05-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "p1a000000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================ projects
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status_explanation", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'new'")),
        sa.Column("owner", sa.String(255), nullable=True),
        sa.Column("owner_other", sa.String(255), nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("category_other", sa.String(255), nullable=True),
        sa.Column("category_other_reason", sa.String(1000), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="project",
    )
    # Self-FK on parent_id (use_alter; targets the same table)
    op.create_foreign_key(
        "fk_projects_parent_id",
        "projects", "projects",
        ["parent_id"], ["id"],
        source_schema="project", referent_schema="project",
        use_alter=True,
    )
    op.create_index("ix_projects_project_code", "projects", ["project_code"], unique=True, schema="project")
    op.create_index("ix_projects_name", "projects", ["name"], schema="project")
    op.create_index("ix_projects_active", "projects", ["active"], schema="project")
    op.create_index("ix_projects_public", "projects", ["public"], schema="project")
    op.create_index("ix_projects_parent_id", "projects", ["parent_id"], schema="project")
    op.create_index("ix_projects_status", "projects", ["status"], schema="project")
    op.create_index("ix_projects_owner", "projects", ["owner"], schema="project")
    op.create_index("ix_projects_category", "projects", ["category"], schema="project")
    op.create_index("ix_projects_start_date", "projects", ["start_date"], schema="project")
    op.create_index("ix_projects_end_date", "projects", ["end_date"], schema="project")
    op.create_index("ix_projects_deleted_at", "projects", ["deleted_at"], schema="project")

    # ============================================================ project_vendors (M:N)
    op.create_table(
        "project_vendors",
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("vendor_id", sa.String(36), nullable=False),  # logical FK to masters.vendors.id
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["project.projects.id"], name="fk_project_vendors_project_id"),
        sa.PrimaryKeyConstraint("project_id", "vendor_id", name="pk_project_vendors"),
        schema="project",
    )
    op.create_index("ix_project_vendors_project_id", "project_vendors", ["project_id"], schema="project")
    op.create_index("ix_project_vendors_vendor_id", "project_vendors", ["vendor_id"], schema="project")

    # ============================================================ project_audit_logs
    op.create_table(
        "project_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("target_kind", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["project.projects.id"], name="fk_pal_project_id"),
        schema="project",
    )
    op.create_index("ix_pal_project_id", "project_audit_logs", ["project_id"], schema="project")
    op.create_index("ix_pal_target", "project_audit_logs", ["target_kind", "target_id"], schema="project")
    op.create_index("ix_pal_actor_user_id", "project_audit_logs", ["actor_user_id"], schema="project")
    op.create_index("ix_pal_created_at", "project_audit_logs", ["created_at"], schema="project")

    # ============================================================ milestones
    op.create_table(
        "milestones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'not_completed'")),
        sa.Column("priority", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.projects.id"], name="fk_milestones_project_id"),
        schema="project",
    )
    op.create_index("idx_milestones_project_live", "milestones", ["project_id", "deleted_at"], schema="project")
    op.create_index("idx_milestones_project_position", "milestones", ["project_id", "position"], schema="project")
    op.create_index(
        "uq_milestones_project_position_live", "milestones",
        ["project_id", "position"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), schema="project",
    )
    op.create_index("ix_milestones_status", "milestones", ["status"], schema="project")
    op.create_index("ix_milestones_priority", "milestones", ["priority"], schema="project")
    op.create_index("ix_milestones_deleted_at", "milestones", ["deleted_at"], schema="project")

    # ============================================================ milestone_dependencies
    op.create_table(
        "milestone_dependencies",
        sa.Column("from_milestone_id", sa.String(36), nullable=False),
        sa.Column("to_milestone_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["from_milestone_id"], ["project.milestones.id"], name="fk_md_from"),
        sa.ForeignKeyConstraint(["to_milestone_id"], ["project.milestones.id"], name="fk_md_to"),
        sa.PrimaryKeyConstraint("from_milestone_id", "to_milestone_id", name="pk_milestone_dependencies"),
        schema="project",
    )
    op.create_index("ix_milestone_dep_from", "milestone_dependencies", ["from_milestone_id"], schema="project")
    op.create_index("ix_milestone_dep_to", "milestone_dependencies", ["to_milestone_id"], schema="project")

    # ============================================================ milestone_vendors (M:N)
    op.create_table(
        "milestone_vendors",
        sa.Column("milestone_id", sa.String(36), nullable=False),
        sa.Column("vendor_id", sa.String(36), nullable=False),  # logical FK
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["milestone_id"], ["project.milestones.id"], name="fk_mv_milestone"),
        sa.PrimaryKeyConstraint("milestone_id", "vendor_id", name="pk_milestone_vendors"),
        schema="project",
    )
    op.create_index("ix_milestone_vendors_milestone_id", "milestone_vendors", ["milestone_id"], schema="project")
    op.create_index("ix_milestone_vendors_vendor_id", "milestone_vendors", ["vendor_id"], schema="project")

    # ============================================================ activities
    op.create_table(
        "activities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("milestone_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(20), nullable=True),
        sa.Column("owner_division", sa.String(32), nullable=True),
        sa.Column("concerned_division", sa.String(32), nullable=True),
        sa.Column("concerned_divisions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("vendor_id", sa.String(36), nullable=True),  # logical FK
        sa.Column("priority", sa.String(16), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("resource_mode", sa.String(10), nullable=True),
        sa.Column("resource_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.projects.id"], name="fk_activities_project_id"),
        sa.ForeignKeyConstraint(["milestone_id"], ["project.milestones.id"], name="fk_activities_milestone_id"),
        sa.CheckConstraint(
            "type IS NULL OR type IN ('standard', 'resource', 'transactional')",
            name="ck_activities_type",
        ),
        sa.CheckConstraint(
            "resource_mode IS NULL OR resource_mode IN ('count', 'details')",
            name="ck_activities_resource_mode",
        ),
        sa.CheckConstraint(
            "resource_count IS NULL OR resource_count >= 1",
            name="ck_activities_resource_count_positive",
        ),
        schema="project",
    )
    op.create_index("idx_activities_milestone_live", "activities", ["milestone_id", "deleted_at"], schema="project")
    op.create_index("idx_activities_milestone_position", "activities", ["milestone_id", "position"], schema="project")
    op.create_index("idx_activities_project_live", "activities", ["project_id", "deleted_at"], schema="project")
    op.create_index(
        "uq_activities_milestone_position_live", "activities",
        ["milestone_id", "position"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), schema="project",
    )
    op.create_index("ix_activities_vendor_id", "activities", ["vendor_id"], schema="project")
    op.create_index("ix_activities_owner_division", "activities", ["owner_division"], schema="project")
    op.create_index("ix_activities_status", "activities", ["status"], schema="project")
    op.create_index("ix_activities_priority", "activities", ["priority"], schema="project")
    op.create_index("ix_activities_deleted_at", "activities", ["deleted_at"], schema="project")

    # ============================================================ activity_dependencies
    op.create_table(
        "activity_dependencies",
        sa.Column("from_activity_id", sa.String(36), nullable=False),
        sa.Column("to_activity_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["from_activity_id"], ["project.activities.id"], name="fk_ad_from"),
        sa.ForeignKeyConstraint(["to_activity_id"], ["project.activities.id"], name="fk_ad_to"),
        sa.PrimaryKeyConstraint("from_activity_id", "to_activity_id", name="pk_activity_dependencies"),
        schema="project",
    )
    op.create_index("ix_activity_dep_from", "activity_dependencies", ["from_activity_id"], schema="project")
    op.create_index("ix_activity_dep_to", "activity_dependencies", ["to_activity_id"], schema="project")

    # ============================================================ activity_resources
    op.create_table(
        "activity_resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("resource_name", sa.String(255), nullable=False),
        sa.Column("onboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_onboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_offboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.String(255), nullable=True),
        sa.Column("designation", sa.String(255), nullable=True),
        sa.Column("job_role", sa.String(255), nullable=True),
        sa.Column("qualification", sa.String(255), nullable=True),
        sa.Column("experience_years", sa.Numeric(4, 1), nullable=True),
        sa.Column("type_of_resource_id", sa.String(36), nullable=True),  # logical FK
        sa.Column("division", sa.String(32), nullable=True),
        sa.Column("division_other", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["activity_id"], ["project.activities.id"], name="fk_ar_activity_id"),
        sa.ForeignKeyConstraint(["project_id"], ["project.projects.id"], name="fk_ar_project_id"),
        schema="project",
    )
    op.create_index(
        "uq_activity_resources_activity_live", "activity_resources",
        ["activity_id"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), schema="project",
    )
    op.create_index("idx_activity_resources_project_live", "activity_resources", ["project_id", "deleted_at"], schema="project")
    op.create_index("ix_activity_resources_type_of_resource_id", "activity_resources", ["type_of_resource_id"], schema="project")

    # ============================================================ tasks
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(20), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("resource_mode", sa.String(10), nullable=True),
        sa.Column("resource_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("priority", sa.String(16), nullable=True),
        sa.Column("assigned_to", sa.String(36), nullable=True),  # logical FK to users.users.id
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.projects.id"], name="fk_tasks_project_id"),
        sa.ForeignKeyConstraint(["activity_id"], ["project.activities.id"], name="fk_tasks_activity_id"),
        sa.CheckConstraint(
            "type IS NULL OR type IN ('standard', 'resource', 'transactional')",
            name="ck_tasks_type",
        ),
        sa.CheckConstraint(
            "resource_mode IS NULL OR resource_mode IN ('count', 'details')",
            name="ck_tasks_resource_mode",
        ),
        sa.CheckConstraint(
            "resource_count IS NULL OR resource_count >= 1",
            name="ck_tasks_resource_count_positive",
        ),
        schema="project",
    )
    op.create_index("idx_tasks_activity_live", "tasks", ["activity_id", "deleted_at"], schema="project")
    op.create_index("idx_tasks_activity_position", "tasks", ["activity_id", "position"], schema="project")
    op.create_index("idx_tasks_project_live", "tasks", ["project_id", "deleted_at"], schema="project")
    op.create_index(
        "uq_tasks_activity_position_live", "tasks",
        ["activity_id", "position"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), schema="project",
    )
    op.create_index("ix_tasks_assigned_to", "tasks", ["assigned_to"], schema="project")
    op.create_index("ix_tasks_status", "tasks", ["status"], schema="project")
    op.create_index("ix_tasks_priority", "tasks", ["priority"], schema="project")
    op.create_index("ix_tasks_deleted_at", "tasks", ["deleted_at"], schema="project")

    # ============================================================ task_dependencies
    op.create_table(
        "task_dependencies",
        sa.Column("from_task_id", sa.String(36), nullable=False),
        sa.Column("to_task_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["from_task_id"], ["project.tasks.id"], name="fk_td_from"),
        sa.ForeignKeyConstraint(["to_task_id"], ["project.tasks.id"], name="fk_td_to"),
        sa.PrimaryKeyConstraint("from_task_id", "to_task_id", name="pk_task_dependencies"),
        schema="project",
    )
    op.create_index("ix_task_dep_from", "task_dependencies", ["from_task_id"], schema="project")
    op.create_index("ix_task_dep_to", "task_dependencies", ["to_task_id"], schema="project")

    # ============================================================ task_resources
    op.create_table(
        "task_resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("resource_name", sa.String(255), nullable=False),
        sa.Column("onboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_onboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_offboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.String(255), nullable=True),
        sa.Column("designation", sa.String(255), nullable=True),
        sa.Column("job_role", sa.String(255), nullable=True),
        sa.Column("qualification", sa.String(255), nullable=True),
        sa.Column("experience_years", sa.Numeric(4, 1), nullable=True),
        sa.Column("type_of_resource_id", sa.String(36), nullable=True),
        sa.Column("division", sa.String(32), nullable=True),
        sa.Column("division_other", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["project.tasks.id"], name="fk_tr_task_id"),
        sa.ForeignKeyConstraint(["project_id"], ["project.projects.id"], name="fk_tr_project_id"),
        schema="project",
    )
    op.create_index(
        "uq_task_resources_task_live", "task_resources",
        ["task_id"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), schema="project",
    )
    op.create_index("idx_task_resources_project_live", "task_resources", ["project_id", "deleted_at"], schema="project")
    op.create_index("ix_task_resources_type_of_resource_id", "task_resources", ["type_of_resource_id"], schema="project")

    # ============================================================ subtasks
    op.create_table(
        "subtasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("parent_subtask_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(20), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("resource_mode", sa.String(10), nullable=True),
        sa.Column("resource_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("priority", sa.String(16), nullable=True),
        sa.Column("assigned_to", sa.String(36), nullable=True),  # logical FK
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.projects.id"], name="fk_subtasks_project_id"),
        sa.ForeignKeyConstraint(["task_id"], ["project.tasks.id"], name="fk_subtasks_task_id"),
        sa.CheckConstraint(
            "type IS NULL OR type IN ('standard', 'resource', 'transactional')",
            name="ck_subtasks_type",
        ),
        sa.CheckConstraint(
            "resource_mode IS NULL OR resource_mode IN ('count', 'details')",
            name="ck_subtasks_resource_mode",
        ),
        sa.CheckConstraint(
            "resource_count IS NULL OR resource_count >= 1",
            name="ck_subtasks_resource_count_positive",
        ),
        schema="project",
    )
    op.create_foreign_key(
        "fk_subtasks_parent_subtask_id",
        "subtasks", "subtasks",
        ["parent_subtask_id"], ["id"],
        source_schema="project", referent_schema="project",
        use_alter=True,
    )
    op.create_index("idx_subtasks_task_live", "subtasks", ["task_id", "deleted_at"], schema="project")
    op.create_index("idx_subtasks_task_position", "subtasks", ["task_id", "position"], schema="project")
    op.create_index("idx_subtasks_project_live", "subtasks", ["project_id", "deleted_at"], schema="project")
    op.create_index("ix_subtasks_parent_subtask_id", "subtasks", ["parent_subtask_id"], schema="project")
    op.create_index(
        "uq_subtasks_task_position_top_live", "subtasks",
        ["task_id", "position"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND parent_subtask_id IS NULL"),
        schema="project",
    )
    op.create_index(
        "uq_subtasks_subtask_position_live", "subtasks",
        ["parent_subtask_id", "position"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND parent_subtask_id IS NOT NULL"),
        schema="project",
    )
    op.create_index("ix_subtasks_assigned_to", "subtasks", ["assigned_to"], schema="project")
    op.create_index("ix_subtasks_status", "subtasks", ["status"], schema="project")
    op.create_index("ix_subtasks_priority", "subtasks", ["priority"], schema="project")
    op.create_index("ix_subtasks_deleted_at", "subtasks", ["deleted_at"], schema="project")

    # ============================================================ subtask_dependencies
    op.create_table(
        "subtask_dependencies",
        sa.Column("from_subtask_id", sa.String(36), nullable=False),
        sa.Column("to_subtask_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["from_subtask_id"], ["project.subtasks.id"], name="fk_sd_from"),
        sa.ForeignKeyConstraint(["to_subtask_id"], ["project.subtasks.id"], name="fk_sd_to"),
        sa.PrimaryKeyConstraint("from_subtask_id", "to_subtask_id", name="pk_subtask_dependencies"),
        schema="project",
    )
    op.create_index("ix_subtask_dep_from", "subtask_dependencies", ["from_subtask_id"], schema="project")
    op.create_index("ix_subtask_dep_to", "subtask_dependencies", ["to_subtask_id"], schema="project")

    # ============================================================ subtask_resources
    op.create_table(
        "subtask_resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subtask_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("resource_name", sa.String(255), nullable=False),
        sa.Column("onboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_onboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_offboard_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.String(255), nullable=True),
        sa.Column("designation", sa.String(255), nullable=True),
        sa.Column("job_role", sa.String(255), nullable=True),
        sa.Column("qualification", sa.String(255), nullable=True),
        sa.Column("experience_years", sa.Numeric(4, 1), nullable=True),
        sa.Column("type_of_resource_id", sa.String(36), nullable=True),
        sa.Column("division", sa.String(32), nullable=True),
        sa.Column("division_other", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["subtask_id"], ["project.subtasks.id"], name="fk_sr_subtask_id"),
        sa.ForeignKeyConstraint(["project_id"], ["project.projects.id"], name="fk_sr_project_id"),
        schema="project",
    )
    op.create_index(
        "uq_subtask_resources_subtask_live", "subtask_resources",
        ["subtask_id"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), schema="project",
    )
    op.create_index("idx_subtask_resources_project_live", "subtask_resources", ["project_id", "deleted_at"], schema="project")
    op.create_index("ix_subtask_resources_type_of_resource_id", "subtask_resources", ["type_of_resource_id"], schema="project")

    # ============================================================ comments
    op.create_table(
        "comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("target_kind", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("author_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(36), nullable=True),
        schema="project",
    )
    op.create_index("idx_comments_target", "comments", ["target_kind", "target_id"], schema="project")
    op.create_index("idx_comments_target_active", "comments", ["target_kind", "target_id", "deleted_at"], schema="project")
    op.create_index("idx_comments_created_at", "comments", ["created_at"], schema="project")
    op.create_index("ix_comments_author_user_id", "comments", ["author_user_id"], schema="project")
    op.create_index("ix_comments_deleted_at", "comments", ["deleted_at"], schema="project")


def downgrade() -> None:
    # Drop in reverse dependency order. use_alter FKs get dropped with their tables.
    for name in (
        "comments",
        "subtask_resources",
        "subtask_dependencies",
        "subtasks",
        "task_resources",
        "task_dependencies",
        "tasks",
        "activity_resources",
        "activity_dependencies",
        "activities",
        "milestone_vendors",
        "milestone_dependencies",
        "milestones",
        "project_audit_logs",
        "project_vendors",
        "projects",
    ):
        op.drop_table(name, schema="project")
