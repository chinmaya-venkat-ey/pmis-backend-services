"""#323 — per-document role-based access control table.

Creates ``project.document_access_rules``. A document (an attachment / body-NULL
``project.comments`` row) with zero live rules is PUBLIC; one or more live rules
make it RESTRICTED to superadmin/admin + the uploader + users matching a rule
(role held at the rule's project/org/division scope). See
``app/models/document_access_rule.py``.

Revision ID: p1a000000034
Revises: p1a000000033
Create Date: 2026-07-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000034"
down_revision: str = "p1a000000033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_access_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("comment_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("role_name", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("division", sa.String(length=120), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="project",
    )
    op.create_index(
        "ix_document_access_rules_comment", "document_access_rules",
        ["comment_id", "deleted_at"], schema="project",
    )
    op.create_index(
        "ix_document_access_rules_project", "document_access_rules",
        ["project_id"], schema="project",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_access_rules_project",
        table_name="document_access_rules", schema="project",
    )
    op.drop_index(
        "ix_document_access_rules_comment",
        table_name="document_access_rules", schema="project",
    )
    op.drop_table("document_access_rules", schema="project")
