"""Create files schema with file_objects and file_audit_logs tables.

Revision ID: 001_create_files_schema
Revises:
Create Date: 2026-05-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_create_files_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create schema.
    op.execute("CREATE SCHEMA IF NOT EXISTS files")

    # ── file_objects ──────────────────────────────────────────────────────────
    op.create_table(
        "file_objects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("folder", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("s3_key", sa.String(1024), nullable=False, unique=True),
        sa.Column("s3_bucket", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("public_url", sa.Text, nullable=True),
        sa.Column("extra_metadata", postgresql.JSONB, nullable=True),
        sa.Column("uploaded_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="files",
    )
    op.create_index("idx_file_objects_folder", "file_objects", ["folder"], schema="files")
    op.create_index("idx_file_objects_entity", "file_objects", ["entity_type", "entity_id"], schema="files")
    op.create_index("idx_file_objects_uploaded_by", "file_objects", ["uploaded_by"], schema="files")
    op.create_index("idx_file_objects_created_at", "file_objects", ["created_at"], schema="files")
    op.create_index("idx_file_objects_deleted_at", "file_objects", ["deleted_at"], schema="files")

    # ── file_audit_logs ───────────────────────────────────────────────────────
    op.create_table(
        "file_audit_logs",
        sa.Column(
            "id",
            sa.BigInteger,
            sa.Sequence("file_audit_logs_id_seq", schema="files"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("file_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("folder", sa.String(255), nullable=True),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("extra_metadata", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="files",
    )
    op.create_index("idx_file_audit_logs_file_id", "file_audit_logs", ["file_id"], schema="files")
    op.create_index("idx_file_audit_logs_actor", "file_audit_logs", ["actor_user_id"], schema="files")
    op.create_index("idx_file_audit_logs_action", "file_audit_logs", ["action"], schema="files")
    op.create_index("idx_file_audit_logs_entity", "file_audit_logs", ["entity_type", "entity_id"], schema="files")
    op.create_index("idx_file_audit_logs_created_at", "file_audit_logs", ["created_at"], schema="files")


def downgrade() -> None:
    op.drop_table("file_audit_logs", schema="files")
    op.drop_table("file_objects", schema="files")
    op.execute("DROP SCHEMA IF EXISTS files CASCADE")
