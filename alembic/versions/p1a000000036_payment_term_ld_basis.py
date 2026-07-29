"""Add ld_basis_percent to project_payment_terms (penalty/LD basis allotment).

Revision ID: p1a000000036
Revises: p1a000000035
Create Date: 2026-07-28

Why:
  The payment page needs to separate a milestone's PENALTY basis from what it is
  actually PAID. ``percent_of_payment`` stays the reduced amount paid this phase
  (the un-paid remainder carries forward); the new ``ld_basis_percent`` is the
  milestone's full allotment of the phase (default even split 100/N, editable per
  RFP), which must total 100% per phase and is the basis LD / penalties compute
  against. Same shape + range CHECK as ``percent_of_payment``
  (mirrors p1a000000007). Nullable — a null resolves to the even split on read.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "p1a000000036"
down_revision = "p1a000000035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_payment_terms",
        sa.Column("ld_basis_percent", sa.Numeric(5, 2), nullable=True),
        schema="project",
    )
    op.create_check_constraint(
        "ck_payment_terms_ld_basis_range", "project_payment_terms",
        "ld_basis_percent IS NULL OR (ld_basis_percent >= 0 AND ld_basis_percent <= 100)",
        schema="project",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payment_terms_ld_basis_range", "project_payment_terms",
        schema="project", type_="check",
    )
    op.drop_column("project_payment_terms", "ld_basis_percent", schema="project")
