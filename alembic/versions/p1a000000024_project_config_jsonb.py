"""Per-project config/checks bag (JSONB).

Revision ID: p1a000000024
Revises: p1a000000023
Create Date: 2026-07-09

Adds ``project.projects.config`` — a JSONB object holding per-project values
that are NOT master-driven (half-day hours, attendance-captured flag,
sandwich-leave flag, leaves-per-frequency count + period, prorated-leaves
flag, ...). Grouped into ONE object so new checks can be added over time
without further migrations. Defaults to an empty object so existing rows keep
a consistent response shape.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "p1a000000024"
down_revision: str = "p1a000000023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="project",
    )


def downgrade() -> None:
    op.drop_column("projects", "config", schema="project")
