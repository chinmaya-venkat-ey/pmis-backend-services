"""Initial schema for pmis-masters-management — creates the 10 catalog tables
under the `masters` Postgres schema.

Tables (per PLAN.md §5.2):
  - divisions
  - vendors
  - resource_types
  - priorities
  - project_categories
  - activity_types
  - activity_statuses
  - milestone_statuses
  - project_status_transitions
  - notification_templates

NO cross-schema foreign keys are created here. masters.vendors.deleted_by
is a logical reference to users.users.id but not enforced at the DB level
(users-svc owns that table and it isn't guaranteed to exist when this
migration runs).

Indexes mirror the per-model __table_args__ declarations.

Built-in row seeds live in the next migration (m1a000000002).

Revision ID: m1a000000001
Revises: None
Create Date: 2026-05-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The `masters` schema itself is created by migrations/00_create_schemas.sql
    # (cross-service one-shot — runs before any per-service alembic).
    # If running this migration in a fresh dev env without that pre-step,
    # uncomment:
    # op.execute("CREATE SCHEMA IF NOT EXISTS masters")

    # ------------------------------------------------------------------ divisions
    op.create_table(
        "divisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_other", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_divisions_code", "divisions", ["code"], unique=True, schema="masters")
    op.create_index("ix_divisions_active", "divisions", ["active"], schema="masters")
    op.create_index("idx_divisions_code_active", "divisions", ["code", "active"], schema="masters")

    # ------------------------------------------------------------------ vendors
    op.create_table(
        "vendors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vendor_code", sa.String(50), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("contact_person", sa.String(255), nullable=True),
        sa.Column("phone_number", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(36), nullable=True),  # logical FK to users.users.id (app-enforced)
        schema="masters",
    )
    op.create_index("ix_vendors_name", "vendors", ["name"], unique=True, schema="masters")
    op.create_index("ix_vendors_vendor_code", "vendors", ["vendor_code"], unique=True, schema="masters")
    op.create_index("ix_vendors_active", "vendors", ["active"], schema="masters")
    op.create_index("ix_vendors_email", "vendors", ["email"], schema="masters")
    op.create_index("ix_vendors_deleted_at", "vendors", ["deleted_at"], schema="masters")
    op.create_index("idx_vendors_active_name", "vendors", ["active", "name"], schema="masters")
    op.create_index("idx_vendors_created_at", "vendors", ["created_at"], schema="masters")

    # ------------------------------------------------------------------ resource_types
    op.create_table(
        "resource_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_resource_types_code", "resource_types", ["code"], unique=True, schema="masters")
    op.create_index("ix_resource_types_active", "resource_types", ["active"], schema="masters")

    # ------------------------------------------------------------------ priorities
    op.create_table(
        "priorities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_priorities_code", "priorities", ["code"], unique=True, schema="masters")
    op.create_index("ix_priorities_active", "priorities", ["active"], schema="masters")
    op.create_index("idx_priorities_active_code", "priorities", ["active", "code"], schema="masters")

    # ------------------------------------------------------------------ project_categories
    op.create_table(
        "project_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_other", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_project_categories_code", "project_categories", ["code"], unique=True, schema="masters")
    op.create_index("ix_project_categories_active", "project_categories", ["active"], schema="masters")

    # ------------------------------------------------------------------ activity_types
    op.create_table(
        "activity_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_activity_types_code", "activity_types", ["code"], unique=True, schema="masters")
    op.create_index("ix_activity_types_active", "activity_types", ["active"], schema="masters")

    # ------------------------------------------------------------------ activity_statuses
    op.create_table(
        "activity_statuses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_activity_statuses_code", "activity_statuses", ["code"], unique=True, schema="masters")
    op.create_index("ix_activity_statuses_active", "activity_statuses", ["active"], schema="masters")

    # ------------------------------------------------------------------ milestone_statuses
    op.create_table(
        "milestone_statuses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_milestone_statuses_code", "milestone_statuses", ["code"], unique=True, schema="masters")
    op.create_index("ix_milestone_statuses_active", "milestone_statuses", ["active"], schema="masters")

    # ------------------------------------------------------------------ project_status_transitions
    # Round-7: FSM gates by PERMISSION CODE (not role name / requires_admin).
    # `permission_code` NULL means "no special perm needed for this edge"
    # (e.g. the initial NULL->'new' seed). Otherwise the caller must hold
    # the named code at the project scope OR globally.
    op.create_table(
        "project_status_transitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("from_status", sa.String(50), nullable=True),  # NULL = initial-status seed
        sa.Column("to_status", sa.String(50), nullable=False),
        sa.Column("permission_code", sa.String(128), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("from_status", "to_status", name="uq_project_status_transitions_edge"),
        schema="masters",
    )
    op.create_index("ix_pst_from_status", "project_status_transitions", ["from_status"], schema="masters")
    op.create_index("ix_pst_to_status", "project_status_transitions", ["to_status"], schema="masters")
    op.create_index("ix_pst_active", "project_status_transitions", ["active"], schema="masters")
    op.create_index("ix_pst_permission_code", "project_status_transitions", ["permission_code"], schema="masters")
    op.create_index("idx_pst_to_status_active", "project_status_transitions", ["to_status", "active"], schema="masters")

    # ------------------------------------------------------------------ notification_templates
    op.create_table(
        "notification_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("template_kind", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_html", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index(
        "ix_notification_templates_template_kind", "notification_templates", ["template_kind"], schema="masters",
    )
    op.create_index(
        "ix_notification_templates_channel", "notification_templates", ["channel"], schema="masters",
    )
    op.create_index(
        "ix_notification_templates_active", "notification_templates", ["active"], schema="masters",
    )
    op.create_index(
        "idx_notification_templates_kind_channel_active",
        "notification_templates",
        ["template_kind", "channel", "active"],
        schema="masters",
    )


def downgrade() -> None:
    """Drop all 10 catalog tables. Cross-service migrations
    (../../../migrations/02_drop_legacy.sql) handle the migrated `public.*`
    cleanup separately; this downgrade is for dev-stack tear-down only."""
    op.drop_table("notification_templates", schema="masters")
    op.drop_table("project_status_transitions", schema="masters")
    op.drop_table("milestone_statuses", schema="masters")
    op.drop_table("activity_statuses", schema="masters")
    op.drop_table("activity_types", schema="masters")
    op.drop_table("project_categories", schema="masters")
    op.drop_table("priorities", schema="masters")
    op.drop_table("resource_types", schema="masters")
    op.drop_table("vendors", schema="masters")
    op.drop_table("divisions", schema="masters")
