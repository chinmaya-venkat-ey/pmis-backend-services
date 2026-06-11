"""Widen contract.sla_attachments.file_id to fit local-storage keys.

The file_id column was sized as ``VARCHAR(36)`` on the assumption that
pmis-file-store would always return bare UUIDs. The LocalFileClient
fallback uses storage keys of the form
``sla-attachments/{uuid}-{sanitised-filename}`` — easily 150+ chars —
so every NFS-backed upload was 500-ing with::

    psycopg2.errors.StringDataRightTruncation:
    value too long for type character varying(36)

Bumping to ``VARCHAR(500)`` matches the file_url column's character
budget. Plain TEXT would also work; we prefer VARCHAR so the existing
index on file_id stays efficient.

Revision ID: 0018_widen_attachment_file_id
Revises: 0017_sla_attachments
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_widen_attachment_file_id"
down_revision = "0017_sla_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sla_attachments",
        "file_id",
        existing_type=sa.String(36),
        type_=sa.String(500),
        existing_nullable=False,
        schema="contract",
    )


def downgrade() -> None:
    op.alter_column(
        "sla_attachments",
        "file_id",
        existing_type=sa.String(500),
        type_=sa.String(36),
        existing_nullable=False,
        schema="contract",
    )
