"""Initial schema for pmis-user-management — creates the 11 owned tables
under the `users` Postgres schema.

Tables (per PLAN.md §5.1):
  - users
  - roles
  - permissions
  - user_roles                 (legacy global-scope; pre-Doc-41)
  - role_permissions
  - user_permissions           (direct grants, additive to role-derived)
  - user_role_assignments      (Doc-41 scoped: global/org/project)
  - revoked_tokens             (JWT blacklist; cross-read by other services)
  - password_reset_tokens
  - otp_codes                  (Q13: moved here from notification-svc)
  - notification_log           (user-svc's audit of dispatch requests)

NO cross-schema FK constraints. user_role_assignments.organization_id and
.project_id are logical refs to masters.vendors.id and project.projects.id
respectively (app-enforced). users.vendor_id is a logical ref to
masters.vendors.id.

Self-FKs WITHIN this schema (users.users.id targets):
  - users.deleted_by                          (soft-delete attribution)
  - user_roles.user_id, .created_by
  - user_permissions.user_id, .created_by
  - user_role_assignments.user_id, .created_by
  - revoked_tokens.user_id
  - password_reset_tokens.user_id
  - otp_codes.user_id
  - notification_log.user_id

All same-schema FKs use `use_alter=True` for users.deleted_by since that
column references its own table.

Revision ID: u1a000000001
Revises: None
Create Date: 2026-05-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "u1a000000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The `users` schema itself is created by migrations/00_create_schemas.sql.
    # Uncomment for fresh dev envs without that pre-step:
    # op.execute("CREATE SCHEMA IF NOT EXISTS users")

    # ----------------------------------------------------------------- users
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_code", sa.String(16), nullable=True),
        sa.Column("login", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(64), nullable=True),
        sa.Column("last_name", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("vendor_id", sa.String(36), nullable=True),  # logical FK to masters.vendors.id
        sa.Column("division", sa.String(64), nullable=True),    # logical FK to masters.divisions.code
        sa.Column("division_other", sa.String(255), nullable=True),
        sa.Column("phone_number", sa.String(32), nullable=True),
        sa.Column("org_role", sa.String(64), nullable=True),
        sa.Column("refresh_token_jti", sa.String(36), nullable=True),
        sa.Column("previous_refresh_token_jti", sa.String(36), nullable=True),
        sa.Column("previous_refresh_token_jti_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(36), nullable=True),
        schema="users",
    )
    # Self-FK with use_alter=True (deferred so it can target itself)
    op.create_foreign_key(
        "fk_users_deleted_by",
        "users", "users",
        ["deleted_by"], ["id"],
        source_schema="users", referent_schema="users",
        use_alter=True,
    )
    op.create_index("ix_users_login", "users", ["login"], unique=True, schema="users")
    op.create_index("ix_users_email", "users", ["email"], unique=True, schema="users")
    op.create_index("ix_users_user_code", "users", ["user_code"], unique=True, schema="users")
    op.create_index("ix_users_status", "users", ["status"], schema="users")
    op.create_index("ix_users_created_at", "users", ["created_at"], schema="users")
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"], schema="users")
    op.create_index("ix_users_vendor_id", "users", ["vendor_id"], schema="users")

    # ----------------------------------------------------------------- roles
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="users",
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True, schema="users")
    op.create_index("ix_roles_builtin", "roles", ["builtin"], schema="users")

    # ----------------------------------------------------------------- permissions
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="users",
    )

    # ----------------------------------------------------------------- user_roles (legacy)
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.id"], name="fk_user_roles_user_id"),
        sa.ForeignKeyConstraint(["role_id"], ["users.roles.id"], name="fk_user_roles_role_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.users.id"], name="fk_user_roles_created_by"),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
        schema="users",
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"], schema="users")
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"], schema="users")

    # ----------------------------------------------------------------- role_permissions
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("permission_code", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["role_id"], ["users.roles.id"], name="fk_role_permissions_role_id"),
        sa.ForeignKeyConstraint(["permission_code"], ["users.permissions.code"], name="fk_role_permissions_permission_code"),
        sa.PrimaryKeyConstraint("role_id", "permission_code", name="pk_role_permissions"),
        schema="users",
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"], schema="users")
    op.create_index("ix_role_permissions_permission_code", "role_permissions", ["permission_code"], schema="users")

    # ----------------------------------------------------------------- user_permissions
    op.create_table(
        "user_permissions",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("permission_code", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.id"], name="fk_user_permissions_user_id"),
        sa.ForeignKeyConstraint(["permission_code"], ["users.permissions.code"], name="fk_user_permissions_permission_code"),
        sa.ForeignKeyConstraint(["created_by"], ["users.users.id"], name="fk_user_permissions_created_by"),
        sa.PrimaryKeyConstraint("user_id", "permission_code", name="pk_user_permissions"),
        schema="users",
    )
    op.create_index("ix_user_permissions_user_id", "user_permissions", ["user_id"], schema="users")
    op.create_index("ix_user_permissions_permission_code", "user_permissions", ["permission_code"], schema="users")

    # ----------------------------------------------------------------- user_role_assignments (Doc-41)
    op.create_table(
        "user_role_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=True),  # logical FK to masters.vendors.id
        sa.Column("project_id", sa.String(36), nullable=True),       # logical FK to project.projects.id
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.id"], name="fk_ura_user_id"),
        sa.ForeignKeyConstraint(["role_id"], ["users.roles.id"], name="fk_ura_role_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.users.id"], name="fk_ura_created_by"),
        sa.CheckConstraint(
            "NOT (organization_id IS NOT NULL AND project_id IS NOT NULL)",
            name="ck_ura_single_scope",
        ),
        sa.UniqueConstraint(
            "user_id", "role_id", "organization_id", "project_id",
            name="uq_ura_user_role_scope",
        ),
        schema="users",
    )
    op.create_index("ix_ura_user_id", "user_role_assignments", ["user_id"], schema="users")
    op.create_index("ix_ura_role_id", "user_role_assignments", ["role_id"], schema="users")
    op.create_index("ix_ura_organization_id", "user_role_assignments", ["organization_id"], schema="users")
    op.create_index("ix_ura_project_id", "user_role_assignments", ["project_id"], schema="users")

    # ----------------------------------------------------------------- revoked_tokens
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.id"], name="fk_revoked_tokens_user_id"),
        schema="users",
    )
    op.create_index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"], schema="users")
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"], schema="users")

    # ----------------------------------------------------------------- password_reset_tokens
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.id"], name="fk_prt_user_id"),
        schema="users",
    )
    op.create_index("ix_prt_token_hash", "password_reset_tokens", ["token_hash"], unique=True, schema="users")
    op.create_index("ix_prt_user_consumed", "password_reset_tokens", ["user_id", "consumed_at"], schema="users")
    op.create_index("ix_prt_expires_at", "password_reset_tokens", ["expires_at"], schema="users")

    # ----------------------------------------------------------------- otp_codes
    op.create_table(
        "otp_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(255), nullable=True),
        sa.Column("ephemeral_token_hash", sa.String(255), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.id"], name="fk_otp_codes_user_id"),
        schema="users",
    )
    op.create_index("ix_otp_ephemeral_token_hash", "otp_codes", ["ephemeral_token_hash"], schema="users")
    op.create_index("ix_otp_user_consumed", "otp_codes", ["user_id", "consumed_at"], schema="users")
    op.create_index("ix_otp_expires_at", "otp_codes", ["expires_at"], schema="users")

    # ----------------------------------------------------------------- notification_log
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("template_kind", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("error", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.id"], name="fk_nl_user_id"),
        schema="users",
    )
    op.create_index("ix_nl_channel", "notification_log", ["channel"], schema="users")
    op.create_index("ix_nl_template_kind", "notification_log", ["template_kind"], schema="users")
    op.create_index("ix_nl_status", "notification_log", ["status"], schema="users")
    op.create_index("ix_nl_created_at", "notification_log", ["created_at"], schema="users")
    op.create_index("ix_nl_user_template", "notification_log", ["user_id", "template_kind"], schema="users")


def downgrade() -> None:
    op.drop_table("notification_log", schema="users")
    op.drop_table("otp_codes", schema="users")
    op.drop_table("password_reset_tokens", schema="users")
    op.drop_table("revoked_tokens", schema="users")
    op.drop_table("user_role_assignments", schema="users")
    op.drop_table("user_permissions", schema="users")
    op.drop_table("role_permissions", schema="users")
    op.drop_table("user_roles", schema="users")
    op.drop_table("permissions", schema="users")
    op.drop_table("roles", schema="users")
    # users.deleted_by self-FK is dropped automatically with the table
    op.drop_table("users", schema="users")
