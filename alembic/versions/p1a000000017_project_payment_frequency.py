"""Project-level payment frequency (one billing frequency per project).

Revision ID: p1a000000017
Revises: p1a000000016
Create Date: 2026-06-26

Frequency moves from per-payment-term to a single project-level value
(``projects.payment_frequency_code``) — it drives every phase's cycle counts
and the time-based carry-forward. Backfilled from each project's most common
non-null payment-term frequency so existing projects keep their setting.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000017"
down_revision: str = "p1a000000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("payment_frequency_code", sa.String(length=32), nullable=True),
        schema="project",
    )
    # Backfill: the most common non-null frequency among each project's live
    # payment terms (ties broken arbitrarily by count, then code).
    op.execute(
        """
        UPDATE project.projects p
        SET payment_frequency_code = sub.frequency_code
        FROM (
            SELECT DISTINCT ON (project_id) project_id, frequency_code
            FROM (
                SELECT project_id, frequency_code, COUNT(*) AS n
                FROM project.project_payment_terms
                WHERE frequency_code IS NOT NULL AND deleted_at IS NULL
                GROUP BY project_id, frequency_code
            ) c
            ORDER BY project_id, n DESC, frequency_code
        ) sub
        WHERE p.id = sub.project_id
        """
    )


def downgrade() -> None:
    op.drop_column("projects", "payment_frequency_code", schema="project")
