"""Create users.audit_logs — append-only RBAC mutation trail (F16).

Revision ID: r015_audit_logs
Revises: r014_expand_pa_pm
Create Date: 2026-06-04

Closes the "no forensic trail" gap from the RBAC audit: role grants /
revokes had no record of who-did-what-when, so the origin of suspect rows
(e.g. admin@project) could not be reconstructed. This table is written by
RoleAssignmentService on every assignment create / delete / bulk-replace.

user-svc owns the table; no other service reads it (no cross-schema mirror).
Additive — no existing table is touched.

Per A19 a real downgrade is implemented (drop the table).

Revision id is 15 chars — under the 32-char alembic version_num cap.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r015_audit_logs"
down_revision: str = "r014_expand_pa_pm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("target_user_id", sa.String(length=36), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="users",
    )
    op.create_index(
        "ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"], schema="users"
    )
    op.create_index(
        "ix_audit_logs_target_user_id", "audit_logs", ["target_user_id"], schema="users"
    )
    op.create_index(
        "ix_audit_logs_created_at", "audit_logs", ["created_at"], schema="users"
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs", schema="users")
    op.drop_index("ix_audit_logs_target_user_id", table_name="audit_logs", schema="users")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs", schema="users")
    op.drop_table("audit_logs", schema="users")
