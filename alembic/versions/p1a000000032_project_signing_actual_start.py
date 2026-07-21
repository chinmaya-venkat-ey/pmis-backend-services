"""Contract signing date (#321) + actual-start remarks (#322) on projects.

Revision ID: p1a000000032
Revises: p1a000000031
Create Date: 2026-07-20

Additive, nullable columns:
  * contract_signing_date — the date the contract was signed (captured at
    project creation; client requirement, bug #321).
  * actual_start_remarks  — reason/remarks for a late actual start, captured
    with the actual start date (bug #322; attachments reuse the project
    attachment path).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000032"
down_revision: str = "p1a000000031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects",
                  sa.Column("contract_signing_date", sa.DateTime(timezone=True), nullable=True),
                  schema="project")
    op.add_column("projects",
                  sa.Column("actual_start_remarks", sa.String(2000), nullable=True),
                  schema="project")


def downgrade() -> None:
    op.drop_column("projects", "actual_start_remarks", schema="project")
    op.drop_column("projects", "contract_signing_date", schema="project")
