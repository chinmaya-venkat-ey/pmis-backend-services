"""Create the masters.designations catalog + seed one row (Consultant).

Revision ID: m1a000000014
Revises: m1a000000013
Create Date: 2026-07-23

A simple job-designation lookup, same shape as resource_types. Only one value
is seeded for now ("consultant"); more can be added via the manage endpoints.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000014"
down_revision = "m1a000000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "designations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="masters",
    )
    op.create_index("ix_designations_code", "designations", ["code"], unique=True, schema="masters")
    op.create_index("ix_designations_active", "designations", ["active"], schema="masters")

    # Seed a single starter value; the real list will be added later.
    op.execute(
        """
        INSERT INTO masters.designations (id, code, name, active)
        VALUES (gen_random_uuid()::text, 'consultant', 'Consultant', true)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_designations_active", table_name="designations", schema="masters")
    op.drop_index("ix_designations_code", table_name="designations", schema="masters")
    op.drop_table("designations", schema="masters")
