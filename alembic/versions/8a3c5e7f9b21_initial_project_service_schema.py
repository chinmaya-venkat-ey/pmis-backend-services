"""initial project-service schema (idempotent)

Revision ID: 8a3c5e7f9b21
Revises:
Create Date: 2026-04-30

Establishes the head of this service's Alembic chain. All
project-management tables (projects, milestones, activities, tasks,
subtasks, comments, attachments, vendors, resource_types, divisions,
project_status_transitions, etc.) already exist in the shared Postgres
because the monolith's own migrations created them long ago.

Each block in ``upgrade()`` is a ``CREATE TABLE IF NOT EXISTS`` so
running this migration against the shared (already-populated) Postgres
is a no-op while running against a fresh DB creates the schema this
service owns. Per-module port commits append the relevant blocks
incrementally.

DOWNGRADE is intentionally a no-op: these tables are shared
infrastructure used by the monolith. Dropping them here would break
the other service. Real teardown happens only after the monolith is
decommissioned.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8a3c5e7f9b21"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Idempotent CREATE blocks for tables this service owns.

    Each block is gated on table existence so the shared Postgres
    (which already has every project-management table from the
    monolith's chain) sees no-ops on every run.

    Currently registered:
    - resource_types               (Phase 2)
    - divisions                    (Phase 3)
    - project_status_transitions   (Phase 3)
    - vendors                      (Phase 4)
    - projects                     (Phase 4)
    - project_vendors              (Phase 4)
    - milestone_vendors            (Phase 4)
    - project_audit_logs           (Phase 5b)
    - milestones                   (Phase 6)
    - activities                   (Phase 7a)
    - activity_resources           (Phase 7a)
    - activity_dependencies        (Phase 7a)
    - tasks                        (Phase 8)
    - task_resources               (Phase 8)
    - task_dependencies            (Phase 8)
    - subtasks                     (Phase 9)
    - subtask_resources            (Phase 9)
    - subtask_dependencies         (Phase 9)
    - comments                     (Phase 11)
    - attachments                  (Phase 12)
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ---- resource_types --------------------------------------------------
    if "resource_types" not in existing_tables:
        op.create_table(
            "resource_types",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code", name="uq_resource_types_code"),
        )
        op.create_index(
            op.f("ix_resource_types_id"), "resource_types", ["id"], unique=False,
        )
        op.create_index(
            op.f("ix_resource_types_code"),
            "resource_types", ["code"], unique=False,
        )
        op.create_index(
            op.f("ix_resource_types_active"),
            "resource_types", ["active"], unique=False,
        )
        op.create_index(
            "idx_resource_types_active_code",
            "resource_types", ["active", "code"], unique=False,
        )

    # ---- divisions -------------------------------------------------------
    if "divisions" not in existing_tables:
        op.create_table(
            "divisions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False),
            sa.Column("is_builtin", sa.Boolean(), nullable=False),
            sa.Column("requires_other", sa.Boolean(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code", name="uq_divisions_code"),
        )
        op.create_index(
            op.f("ix_divisions_code"), "divisions", ["code"], unique=False,
        )
        op.create_index(
            op.f("ix_divisions_active"),
            "divisions", ["active"], unique=False,
        )
        op.create_index(
            "idx_divisions_code_active",
            "divisions", ["code", "active"], unique=False,
        )

    # ---- project_status_transitions --------------------------------------
    if "project_status_transitions" not in existing_tables:
        op.create_table(
            "project_status_transitions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("from_status", sa.String(length=50), nullable=True),
            sa.Column("to_status", sa.String(length=50), nullable=False),
            sa.Column("requires_admin", sa.Boolean(), nullable=False),
            sa.Column("version_only", sa.Boolean(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "from_status", "to_status",
                name="uq_project_status_transitions_edge",
            ),
        )
        op.create_index(
            op.f("ix_project_status_transitions_from_status"),
            "project_status_transitions", ["from_status"], unique=False,
        )
        op.create_index(
            op.f("ix_project_status_transitions_to_status"),
            "project_status_transitions", ["to_status"], unique=False,
        )
        op.create_index(
            op.f("ix_project_status_transitions_active"),
            "project_status_transitions", ["active"], unique=False,
        )
        op.create_index(
            "idx_pst_to_status_active",
            "project_status_transitions", ["to_status", "active"], unique=False,
        )

    # ---- vendors ---------------------------------------------------------
    if "vendors" not in existing_tables:
        op.create_table(
            "vendors",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("contact_person", sa.String(length=255), nullable=True),
            sa.Column("phone_number", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_by", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uq_vendors_name"),
        )
        op.create_index(op.f("ix_vendors_id"), "vendors", ["id"], unique=False)
        op.create_index(op.f("ix_vendors_name"), "vendors", ["name"], unique=False)
        op.create_index(op.f("ix_vendors_active"), "vendors", ["active"], unique=False)
        op.create_index(op.f("ix_vendors_email"), "vendors", ["email"], unique=False)
        op.create_index(
            op.f("ix_vendors_created_at"), "vendors", ["created_at"], unique=False,
        )
        op.create_index(
            op.f("ix_vendors_deleted_at"), "vendors", ["deleted_at"], unique=False,
        )
        op.create_index(
            "idx_vendors_active_name", "vendors", ["active", "name"], unique=False,
        )

    # ---- projects --------------------------------------------------------
    # Minimal schema — no FKs to users.id (those columns stay as plain
    # Integer). Self-FKs (parent_id, version_of, baseline_id → projects.id)
    # ARE declared.
    if "projects" not in existing_tables:
        op.create_table(
            "projects",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_code", sa.String(length=30), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("public", sa.Boolean(), nullable=False),
            sa.Column("status_explanation", sa.Text(), nullable=True),
            sa.Column("parent_id", sa.String(length=36), nullable=True),
            sa.Column("version_of", sa.String(length=36), nullable=True),
            sa.Column("baseline_id", sa.String(length=36), nullable=True),
            sa.Column("version_no", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("owner", sa.String(length=255), nullable=True),
            sa.Column("owner_other", sa.String(length=255), nullable=True),
            sa.Column("category", sa.String(length=50), nullable=True),
            sa.Column("category_other", sa.String(length=255), nullable=True),
            sa.Column("category_other_reason", sa.String(length=1000), nullable=True),
            sa.Column("start_date", sa.DateTime(), nullable=True),
            sa.Column("end_date", sa.DateTime(), nullable=True),
            sa.Column("actual_start_date", sa.DateTime(), nullable=True),
            sa.Column("actual_end_date", sa.DateTime(), nullable=True),
            sa.Column("is_version", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["parent_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["version_of"], ["projects.id"]),
            sa.ForeignKeyConstraint(["baseline_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_code", name="uq_projects_project_code"),
        )
        op.create_index(op.f("ix_projects_id"), "projects", ["id"], unique=False)
        op.create_index(
            op.f("ix_projects_project_code"), "projects", ["project_code"], unique=False,
        )
        op.create_index(op.f("ix_projects_name"), "projects", ["name"], unique=False)
        op.create_index(op.f("ix_projects_status"), "projects", ["status"], unique=False)
        op.create_index(op.f("ix_projects_owner"), "projects", ["owner"], unique=False)
        op.create_index(
            op.f("ix_projects_category"), "projects", ["category"], unique=False,
        )
        op.create_index(
            op.f("ix_projects_start_date"), "projects", ["start_date"], unique=False,
        )
        op.create_index(
            op.f("ix_projects_end_date"), "projects", ["end_date"], unique=False,
        )
        op.create_index(
            op.f("ix_projects_is_version"), "projects", ["is_version"], unique=False,
        )
        op.create_index(
            op.f("ix_projects_version_of"), "projects", ["version_of"], unique=False,
        )
        op.create_index(
            op.f("ix_projects_baseline_id"), "projects", ["baseline_id"], unique=False,
        )
        op.create_index(
            op.f("ix_projects_parent_id"), "projects", ["parent_id"], unique=False,
        )
        op.create_index(
            op.f("ix_projects_deleted_at"), "projects", ["deleted_at"], unique=False,
        )

    # ---- project_vendors -------------------------------------------------
    if "project_vendors" not in existing_tables:
        op.create_table(
            "project_vendors",
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("vendor_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"]),
            sa.PrimaryKeyConstraint("project_id", "vendor_id"),
        )
        op.create_index(
            "idx_project_vendors_project", "project_vendors",
            ["project_id"], unique=False,
        )
        op.create_index(
            "idx_project_vendors_vendor", "project_vendors",
            ["vendor_id"], unique=False,
        )

    # ---- milestone_vendors ----------------------------------------------
    # FK to milestones.id NOT declared (milestones table is owned by the
    # monolith for now and lands in Phase 6). The shared Postgres has the
    # constraint; the SQLite test DB skips it.
    if "milestone_vendors" not in existing_tables:
        op.create_table(
            "milestone_vendors",
            sa.Column("milestone_id", sa.String(length=36), nullable=False),
            sa.Column("vendor_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"]),
            sa.PrimaryKeyConstraint("milestone_id", "vendor_id"),
        )
        op.create_index(
            "idx_milestone_vendors_milestone", "milestone_vendors",
            ["milestone_id"], unique=False,
        )
        op.create_index(
            "idx_milestone_vendors_vendor", "milestone_vendors",
            ["vendor_id"], unique=False,
        )

    # ---- project_audit_logs --------------------------------------------
    # FK to users.id intentionally NOT declared (project-service does not
    # own UserModel). Shared Postgres enforces the constraint at runtime.
    if "project_audit_logs" not in existing_tables:
        op.create_table(
            "project_audit_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("before", sa.JSON(), nullable=True),
            sa.Column("after", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_project_audit_logs_id"),
            "project_audit_logs", ["id"], unique=False,
        )
        op.create_index(
            op.f("ix_project_audit_logs_project_id"),
            "project_audit_logs", ["project_id"], unique=False,
        )
        op.create_index(
            op.f("ix_project_audit_logs_actor_id"),
            "project_audit_logs", ["actor_id"], unique=False,
        )
        op.create_index(
            op.f("ix_project_audit_logs_action"),
            "project_audit_logs", ["action"], unique=False,
        )
        op.create_index(
            op.f("ix_project_audit_logs_created_at"),
            "project_audit_logs", ["created_at"], unique=False,
        )
        op.create_index(
            "idx_project_audit_logs_project_id",
            "project_audit_logs", ["project_id"], unique=False,
        )
        op.create_index(
            "idx_project_audit_logs_created_at",
            "project_audit_logs", ["created_at"], unique=False,
        )

    # ---- milestones -----------------------------------------------------
    # FK to users.id NOT declared (ORM-side). Self-FK on cloned_from_id +
    # FK to projects.id ARE declared.
    if "milestones" not in existing_tables:
        op.create_table(
            "milestones",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("start_date", sa.DateTime(), nullable=False),
            sa.Column("end_date", sa.DateTime(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("depends", sa.JSON(), nullable=True),
            sa.Column("cloned_from_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["cloned_from_id"], ["milestones.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_milestones_id"), "milestones", ["id"], unique=False)
        op.create_index(
            op.f("ix_milestones_project_id"),
            "milestones", ["project_id"], unique=False,
        )
        op.create_index(
            op.f("ix_milestones_name"), "milestones", ["name"], unique=False,
        )
        op.create_index(
            op.f("ix_milestones_status"), "milestones", ["status"], unique=False,
        )
        op.create_index(
            op.f("ix_milestones_cloned_from_id"),
            "milestones", ["cloned_from_id"], unique=False,
        )
        op.create_index(
            op.f("ix_milestones_deleted_at"),
            "milestones", ["deleted_at"], unique=False,
        )
        op.create_index(
            "idx_milestones_project_live",
            "milestones", ["project_id", "deleted_at"], unique=False,
        )
        op.create_index(
            "idx_milestones_project_position",
            "milestones", ["project_id", "position"], unique=False,
        )

    # ---- activities -----------------------------------------------------
    if "activities" not in existing_tables:
        op.create_table(
            "activities",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("milestone_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("type", sa.String(length=20), nullable=False),
            sa.Column("start_date", sa.DateTime(), nullable=False),
            sa.Column("end_date", sa.DateTime(), nullable=False),
            sa.Column("actual_start_date", sa.DateTime(), nullable=True),
            sa.Column("actual_end_date", sa.DateTime(), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("resource_mode", sa.String(length=10), nullable=True),
            sa.Column("resource_count", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("cloned_from_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "type IN ('standard', 'resource', 'transactional')",
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
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["milestone_id"], ["milestones.id"]),
            sa.ForeignKeyConstraint(["cloned_from_id"], ["activities.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_activities_id"), "activities", ["id"], unique=False)
        op.create_index(
            op.f("ix_activities_project_id"), "activities", ["project_id"], unique=False,
        )
        op.create_index(
            op.f("ix_activities_milestone_id"), "activities", ["milestone_id"], unique=False,
        )
        op.create_index(op.f("ix_activities_name"), "activities", ["name"], unique=False)
        op.create_index(
            op.f("ix_activities_status"), "activities", ["status"], unique=False,
        )
        op.create_index(
            op.f("ix_activities_cloned_from_id"),
            "activities", ["cloned_from_id"], unique=False,
        )
        op.create_index(
            op.f("ix_activities_deleted_at"),
            "activities", ["deleted_at"], unique=False,
        )
        op.create_index(
            "idx_activities_milestone_live",
            "activities", ["milestone_id", "deleted_at"], unique=False,
        )
        op.create_index(
            "idx_activities_milestone_position",
            "activities", ["milestone_id", "position"], unique=False,
        )
        op.create_index(
            "idx_activities_project_live",
            "activities", ["project_id", "deleted_at"], unique=False,
        )

    # ---- activity_resources --------------------------------------------
    if "activity_resources" not in existing_tables:
        op.create_table(
            "activity_resources",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("activity_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("resource_name", sa.String(length=255), nullable=False),
            sa.Column("onboard_date", sa.DateTime(), nullable=True),
            sa.Column("actual_onboard_date", sa.DateTime(), nullable=True),
            sa.Column("offboard_date", sa.DateTime(), nullable=True),
            sa.Column("actual_offboard_date", sa.DateTime(), nullable=True),
            sa.Column("position", sa.String(length=255), nullable=True),
            sa.Column("designation", sa.String(length=255), nullable=True),
            sa.Column("job_role", sa.String(length=255), nullable=True),
            sa.Column("qualification", sa.String(length=255), nullable=True),
            sa.Column("experience_years", sa.Numeric(4, 1), nullable=True),
            sa.Column("type_of_resource_id", sa.String(length=36), nullable=True),
            sa.Column("division", sa.String(length=32), nullable=True),
            sa.Column("division_other", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["type_of_resource_id"], ["resource_types.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_activity_resources_id"),
            "activity_resources", ["id"], unique=False,
        )
        op.create_index(
            op.f("ix_activity_resources_activity_id"),
            "activity_resources", ["activity_id"], unique=False,
        )
        op.create_index(
            op.f("ix_activity_resources_project_id"),
            "activity_resources", ["project_id"], unique=False,
        )
        op.create_index(
            op.f("ix_activity_resources_type_of_resource_id"),
            "activity_resources", ["type_of_resource_id"], unique=False,
        )
        op.create_index(
            op.f("ix_activity_resources_deleted_at"),
            "activity_resources", ["deleted_at"], unique=False,
        )
        op.create_index(
            "idx_activity_resources_project_live",
            "activity_resources", ["project_id", "deleted_at"], unique=False,
        )
        # Partial unique index — one live resource per activity.
        op.create_index(
            "uq_activity_resources_activity_live",
            "activity_resources", ["activity_id"], unique=True,
            sqlite_where=sa.text("deleted_at IS NULL"),
            postgresql_where=sa.text("deleted_at IS NULL"),
        )

    # ---- activity_dependencies -----------------------------------------
    if "activity_dependencies" not in existing_tables:
        op.create_table(
            "activity_dependencies",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_activity_id", sa.String(length=36), nullable=False),
            sa.Column("target_activity_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["source_activity_id"], ["activities.id"]),
            sa.ForeignKeyConstraint(["target_activity_id"], ["activities.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_activity_dependencies_id"),
            "activity_dependencies", ["id"], unique=False,
        )
        op.create_index(
            op.f("ix_activity_dependencies_source_activity_id"),
            "activity_dependencies", ["source_activity_id"], unique=False,
        )
        op.create_index(
            op.f("ix_activity_dependencies_target_activity_id"),
            "activity_dependencies", ["target_activity_id"], unique=False,
        )
        op.create_index(
            op.f("ix_activity_dependencies_project_id"),
            "activity_dependencies", ["project_id"], unique=False,
        )
        op.create_index(
            op.f("ix_activity_dependencies_deleted_at"),
            "activity_dependencies", ["deleted_at"], unique=False,
        )
        op.create_index(
            "idx_activity_deps_source_live",
            "activity_dependencies",
            ["source_activity_id", "deleted_at"], unique=False,
        )
        op.create_index(
            "idx_activity_deps_target_live",
            "activity_dependencies",
            ["target_activity_id", "deleted_at"], unique=False,
        )
        op.create_index(
            "idx_activity_deps_project_live",
            "activity_dependencies",
            ["project_id", "deleted_at"], unique=False,
        )
        # Partial unique index — one live edge per (source, target).
        op.create_index(
            "uq_activity_deps_pair_live",
            "activity_dependencies",
            ["source_activity_id", "target_activity_id"], unique=True,
            sqlite_where=sa.text("deleted_at IS NULL"),
            postgresql_where=sa.text("deleted_at IS NULL"),
        )


    # ---- tasks (Phase 8) -----------------------------------------------
    if "tasks" not in existing_tables:
        op.create_table(
            "tasks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("activity_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("type", sa.String(length=20), nullable=False),
            sa.Column("start_date", sa.DateTime(), nullable=False),
            sa.Column("end_date", sa.DateTime(), nullable=False),
            sa.Column("actual_start_date", sa.DateTime(), nullable=True),
            sa.Column("actual_end_date", sa.DateTime(), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("resource_mode", sa.String(length=10), nullable=True),
            sa.Column("resource_count", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            # FKs to users.id NOT declared (project-service doesn't own UserModel).
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
            sa.CheckConstraint(
                "type IN ('standard', 'resource', 'transactional')",
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
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_tasks_id"), "tasks", ["id"], unique=False)
        op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
        op.create_index(op.f("ix_tasks_activity_id"), "tasks", ["activity_id"], unique=False)
        op.create_index(op.f("ix_tasks_name"), "tasks", ["name"], unique=False)
        op.create_index(op.f("ix_tasks_deleted_at"), "tasks", ["deleted_at"], unique=False)
        op.create_index("idx_tasks_activity_live", "tasks", ["activity_id", "deleted_at"], unique=False)
        op.create_index("idx_tasks_activity_position", "tasks", ["activity_id", "position"], unique=False)
        op.create_index("idx_tasks_project_live", "tasks", ["project_id", "deleted_at"], unique=False)

    # ---- task_resources (Phase 8) --------------------------------------
    if "task_resources" not in existing_tables:
        op.create_table(
            "task_resources",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("resource_name", sa.String(length=255), nullable=False),
            sa.Column("onboard_date", sa.DateTime(), nullable=True),
            sa.Column("actual_onboard_date", sa.DateTime(), nullable=True),
            sa.Column("offboard_date", sa.DateTime(), nullable=True),
            sa.Column("actual_offboard_date", sa.DateTime(), nullable=True),
            sa.Column("position", sa.String(length=255), nullable=True),
            sa.Column("designation", sa.String(length=255), nullable=True),
            sa.Column("job_role", sa.String(length=255), nullable=True),
            sa.Column("qualification", sa.String(length=255), nullable=True),
            sa.Column("experience_years", sa.Numeric(precision=4, scale=1), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_task_resources_id"), "task_resources", ["id"], unique=False)
        op.create_index(op.f("ix_task_resources_task_id"), "task_resources", ["task_id"], unique=False)
        op.create_index(op.f("ix_task_resources_project_id"), "task_resources", ["project_id"], unique=False)
        op.create_index(op.f("ix_task_resources_deleted_at"), "task_resources", ["deleted_at"], unique=False)
        op.create_index(
            "uq_task_resources_task_live",
            "task_resources", ["task_id"], unique=True,
            sqlite_where=sa.text("deleted_at IS NULL"),
            postgresql_where=sa.text("deleted_at IS NULL"),
        )
        op.create_index(
            "idx_task_resources_project_live",
            "task_resources", ["project_id", "deleted_at"], unique=False,
        )

    # ---- task_dependencies (Phase 8) -----------------------------------
    if "task_dependencies" not in existing_tables:
        op.create_table(
            "task_dependencies",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_task_id", sa.String(length=36), nullable=False),
            sa.Column("target_task_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["source_task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["target_task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_task_dependencies_id"), "task_dependencies", ["id"], unique=False)
        op.create_index(op.f("ix_task_dependencies_source_task_id"), "task_dependencies", ["source_task_id"], unique=False)
        op.create_index(op.f("ix_task_dependencies_target_task_id"), "task_dependencies", ["target_task_id"], unique=False)
        op.create_index(op.f("ix_task_dependencies_project_id"), "task_dependencies", ["project_id"], unique=False)
        op.create_index(op.f("ix_task_dependencies_deleted_at"), "task_dependencies", ["deleted_at"], unique=False)
        op.create_index("idx_task_deps_source_live", "task_dependencies", ["source_task_id", "deleted_at"], unique=False)
        op.create_index("idx_task_deps_target_live", "task_dependencies", ["target_task_id", "deleted_at"], unique=False)
        op.create_index("idx_task_deps_project_live", "task_dependencies", ["project_id", "deleted_at"], unique=False)
        op.create_index(
            "uq_task_deps_pair_live",
            "task_dependencies",
            ["source_task_id", "target_task_id"], unique=True,
            sqlite_where=sa.text("deleted_at IS NULL"),
            postgresql_where=sa.text("deleted_at IS NULL"),
        )


    # ---- subtasks (Phase 9) --------------------------------------------
    if "subtasks" not in existing_tables:
        op.create_table(
            "subtasks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("type", sa.String(length=20), nullable=False),
            sa.Column("start_date", sa.DateTime(), nullable=False),
            sa.Column("end_date", sa.DateTime(), nullable=False),
            sa.Column("actual_start_date", sa.DateTime(), nullable=True),
            sa.Column("actual_end_date", sa.DateTime(), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("resource_mode", sa.String(length=10), nullable=True),
            sa.Column("resource_count", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.CheckConstraint(
                "type IN ('standard', 'resource', 'transactional')",
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
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_subtasks_id"), "subtasks", ["id"], unique=False)
        op.create_index(op.f("ix_subtasks_project_id"), "subtasks", ["project_id"], unique=False)
        op.create_index(op.f("ix_subtasks_task_id"), "subtasks", ["task_id"], unique=False)
        op.create_index(op.f("ix_subtasks_name"), "subtasks", ["name"], unique=False)
        op.create_index(op.f("ix_subtasks_deleted_at"), "subtasks", ["deleted_at"], unique=False)
        op.create_index("idx_subtasks_task_live", "subtasks", ["task_id", "deleted_at"], unique=False)
        op.create_index("idx_subtasks_task_position", "subtasks", ["task_id", "position"], unique=False)
        op.create_index("idx_subtasks_project_live", "subtasks", ["project_id", "deleted_at"], unique=False)

    # ---- subtask_resources (Phase 9) -----------------------------------
    if "subtask_resources" not in existing_tables:
        op.create_table(
            "subtask_resources",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("subtask_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("resource_name", sa.String(length=255), nullable=False),
            sa.Column("onboard_date", sa.DateTime(), nullable=True),
            sa.Column("actual_onboard_date", sa.DateTime(), nullable=True),
            sa.Column("offboard_date", sa.DateTime(), nullable=True),
            sa.Column("actual_offboard_date", sa.DateTime(), nullable=True),
            sa.Column("position", sa.String(length=255), nullable=True),
            sa.Column("designation", sa.String(length=255), nullable=True),
            sa.Column("job_role", sa.String(length=255), nullable=True),
            sa.Column("qualification", sa.String(length=255), nullable=True),
            sa.Column("experience_years", sa.Numeric(precision=4, scale=1), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["subtask_id"], ["subtasks.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_subtask_resources_id"), "subtask_resources", ["id"], unique=False)
        op.create_index(op.f("ix_subtask_resources_subtask_id"), "subtask_resources", ["subtask_id"], unique=False)
        op.create_index(op.f("ix_subtask_resources_project_id"), "subtask_resources", ["project_id"], unique=False)
        op.create_index(op.f("ix_subtask_resources_deleted_at"), "subtask_resources", ["deleted_at"], unique=False)
        op.create_index(
            "uq_subtask_resources_subtask_live",
            "subtask_resources", ["subtask_id"], unique=True,
            sqlite_where=sa.text("deleted_at IS NULL"),
            postgresql_where=sa.text("deleted_at IS NULL"),
        )
        op.create_index(
            "idx_subtask_resources_project_live",
            "subtask_resources", ["project_id", "deleted_at"], unique=False,
        )

    # ---- subtask_dependencies (Phase 9) --------------------------------
    if "subtask_dependencies" not in existing_tables:
        op.create_table(
            "subtask_dependencies",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_subtask_id", sa.String(length=36), nullable=False),
            sa.Column("target_subtask_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["source_subtask_id"], ["subtasks.id"]),
            sa.ForeignKeyConstraint(["target_subtask_id"], ["subtasks.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_subtask_dependencies_id"), "subtask_dependencies", ["id"], unique=False)
        op.create_index(op.f("ix_subtask_dependencies_source_subtask_id"), "subtask_dependencies", ["source_subtask_id"], unique=False)
        op.create_index(op.f("ix_subtask_dependencies_target_subtask_id"), "subtask_dependencies", ["target_subtask_id"], unique=False)
        op.create_index(op.f("ix_subtask_dependencies_project_id"), "subtask_dependencies", ["project_id"], unique=False)
        op.create_index(op.f("ix_subtask_dependencies_deleted_at"), "subtask_dependencies", ["deleted_at"], unique=False)
        op.create_index("idx_subtask_deps_source_live", "subtask_dependencies", ["source_subtask_id", "deleted_at"], unique=False)
        op.create_index("idx_subtask_deps_target_live", "subtask_dependencies", ["target_subtask_id", "deleted_at"], unique=False)
        op.create_index("idx_subtask_deps_project_live", "subtask_dependencies", ["project_id", "deleted_at"], unique=False)
        op.create_index(
            "uq_subtask_deps_pair_live",
            "subtask_dependencies",
            ["source_subtask_id", "target_subtask_id"], unique=True,
            sqlite_where=sa.text("deleted_at IS NULL"),
            postgresql_where=sa.text("deleted_at IS NULL"),
        )


    # ---- comments (Phase 11) -------------------------------------------
    if "comments" not in existing_tables:
        op.create_table(
            "comments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("target_kind", sa.String(length=20), nullable=False),
            sa.Column("target_id", sa.String(length=36), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            # FKs to users.id NOT declared (project-service doesn't own UserModel).
            sa.Column("author_user_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_by", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_comments_author_user_id"),
            "comments", ["author_user_id"], unique=False,
        )
        op.create_index(
            op.f("ix_comments_deleted_at"),
            "comments", ["deleted_at"], unique=False,
        )
        op.create_index(
            "idx_comments_target",
            "comments", ["target_kind", "target_id"], unique=False,
        )
        op.create_index(
            "idx_comments_target_active",
            "comments", ["target_kind", "target_id", "deleted_at"],
            unique=False,
        )
        op.create_index(
            "idx_comments_created_at",
            "comments", ["created_at"], unique=False,
        )


    # ---- attachments (Phase 12) ----------------------------------------
    if "attachments" not in existing_tables:
        op.create_table(
            "attachments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("comment_id", sa.String(length=36), nullable=True),
            sa.Column("target_kind", sa.String(length=20), nullable=True),
            sa.Column("target_id", sa.String(length=36), nullable=True),
            sa.Column("original_filename", sa.String(length=500), nullable=False),
            sa.Column("storage_key", sa.String(length=500), nullable=False),
            sa.Column("mime_type", sa.String(length=100), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            # FKs to users.id NOT declared.
            sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["comment_id"], ["comments.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("storage_key", name="uq_attachments_storage_key"),
        )
        op.create_index(
            op.f("ix_attachments_comment_id"),
            "attachments", ["comment_id"], unique=False,
        )
        op.create_index(
            op.f("ix_attachments_uploaded_by_user_id"),
            "attachments", ["uploaded_by_user_id"], unique=False,
        )
        op.create_index(
            op.f("ix_attachments_deleted_at"),
            "attachments", ["deleted_at"], unique=False,
        )
        op.create_index(
            "idx_attachments_target",
            "attachments", ["target_kind", "target_id"], unique=False,
        )
        op.create_index(
            "idx_attachments_target_active",
            "attachments", ["target_kind", "target_id", "deleted_at"],
            unique=False,
        )
        op.create_index(
            "idx_attachments_uploaded_at",
            "attachments", ["uploaded_at"], unique=False,
        )


def downgrade() -> None:
    """Intentionally a no-op — see module docstring."""
    pass
