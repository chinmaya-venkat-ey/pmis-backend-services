"""Per-phase one-time allocation config on the phase-config row.

Revision ID: p1a000000021
Revises: p1a000000020
Create Date: 2026-07-01

One-time cost is no longer auto-folded into the first phase. It becomes a
project pool that phases opt into: ``one_time_enabled`` + ``one_time_mode``
('percent' | 'amount') + ``one_time_value``. The chronologically last phase
auto-absorbs the unallocated remainder (computed, not stored).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000021"
down_revision: str = "p1a000000020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_phase_qrg",
                  sa.Column("one_time_enabled", sa.Boolean(), nullable=False,
                            server_default=sa.text("false")),
                  schema="project")
    op.add_column("project_phase_qrg",
                  sa.Column("one_time_mode", sa.String(8), nullable=True),
                  schema="project")
    op.add_column("project_phase_qrg",
                  sa.Column("one_time_value", sa.Numeric(18, 2), nullable=True),
                  schema="project")


def downgrade() -> None:
    op.drop_column("project_phase_qrg", "one_time_value", schema="project")
    op.drop_column("project_phase_qrg", "one_time_mode", schema="project")
    op.drop_column("project_phase_qrg", "one_time_enabled", schema="project")
