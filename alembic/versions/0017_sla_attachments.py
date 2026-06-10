"""Add contract.sla_attachments — image attachments per SLA template.

An SLA template can carry 0..N image attachments (screenshots from the
RFP, contract page scans, evidence shots, etc.). The actual bytes live in
pmis-file-store (S3 microservice). We persist only the filestore handle
plus a cached download URL — never the underlying S3 path.

  file_id           pmis-file-store's UUID for the object (canonical handle).
                    Used to refresh download URLs and to soft-delete the
                    file when the attachment row is removed.
  file_url          The most recent download URL filestore returned.
                    Returned as-is on list. FE calls
                    POST /attachments/{id}/refresh-url when it expires.
  caption           Optional user-supplied label, max 500 chars.

Why an `ON DELETE CASCADE` from sla_id?
  When an SLA template is hard-deleted (rare — we soft-delete in practice)
  its attachments go too. For soft-deletes we don't touch attachments;
  the SLA detail view filters them based on `sla_definitions.status`.

Revision ID: 0017_sla_attachments
Revises: 0016_sla_placeholders
Create Date: 2026-06-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_sla_attachments"
down_revision = "0016_sla_placeholders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sla_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sla_id",
            sa.String(36),
            sa.ForeignKey(
                "contract.sla_definitions.id",
                ondelete="CASCADE",
                name="fk_sla_attachments_sla_id",
            ),
            nullable=False,
        ),
        sa.Column("file_id", sa.String(36), nullable=False),
        sa.Column("file_url", sa.Text, nullable=False),
        sa.Column("original_filename", sa.String(255)),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("caption", sa.String(500)),
        sa.Column("uploaded_by", sa.String(36)),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        schema="contract",
    )
    # Partial index: hot path is "live attachments for this SLA". Indexing
    # deleted rows wastes space because the soft-delete tombstones never
    # appear in normal queries.
    op.execute(
        'CREATE INDEX ix_sla_attachments_sla_id_live '
        'ON contract.sla_attachments (sla_id) '
        'WHERE deleted_at IS NULL'
    )
    op.create_index(
        "ix_sla_attachments_file_id",
        "sla_attachments",
        ["file_id"],
        schema="contract",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sla_attachments_file_id",
        table_name="sla_attachments",
        schema="contract",
    )
    op.execute("DROP INDEX IF EXISTS contract.ix_sla_attachments_sla_id_live")
    op.drop_table("sla_attachments", schema="contract")
