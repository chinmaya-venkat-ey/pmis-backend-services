"""Remove the division free-text "others" path.

Revision ID: p1a000000012
Revises: p1a000000011
Create Date: 2026-06-05

Why:
  The "Others (free text)" division option is removed. Divisions must be
  picked from the real masters.divisions catalog. This migration:

    1. Backfills away any legacy ``'others'`` selections:
       - projects.owner = 'others'            -> NULL
       - activities.owner_division = 'others' -> NULL
       - activities.concerned_divisions       -> drop any 'others' element
    2. Drops the now-unused free-text companion columns:
       - projects.owner_other
       - activities.owner_division_other
       - activities.concerned_division_other

  Order matters: backfill first (while the columns still exist), then drop.

  Downgrade re-adds the columns (nullable, empty). The dropped free-text
  values and the nulled 'others' selections are NOT restored — they have
  no valid catalog division to map back to.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000012"
down_revision: str = "p1a000000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Backfill legacy 'others' selections away.
    op.execute(sa.text(
        "UPDATE project.projects SET owner = NULL WHERE lower(owner) = 'others'"
    ))
    op.execute(sa.text(
        "UPDATE project.activities SET owner_division = NULL "
        "WHERE lower(owner_division) = 'others'"
    ))
    # Drop any 'others' element (case-insensitive) from the concerned_divisions
    # JSONB array, leaving the remaining real division codes intact.
    op.execute(sa.text("""
        UPDATE project.activities
           SET concerned_divisions = COALESCE((
               SELECT jsonb_agg(elem)
                 FROM jsonb_array_elements_text(concerned_divisions) AS elem
                WHERE lower(elem) <> 'others'
           ), '[]'::jsonb)
         WHERE concerned_divisions IS NOT NULL
           AND concerned_divisions::text ILIKE '%others%'
    """))

    # 2. Drop the free-text companion columns.
    op.drop_column("activities", "concerned_division_other", schema="project")
    op.drop_column("activities", "owner_division_other", schema="project")
    op.drop_column("projects", "owner_other", schema="project")


def downgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("owner_other", sa.String(length=255), nullable=True),
        schema="project",
    )
    op.add_column(
        "activities",
        sa.Column("owner_division_other", sa.String(length=255), nullable=True),
        schema="project",
    )
    op.add_column(
        "activities",
        sa.Column("concerned_division_other", sa.String(length=255), nullable=True),
        schema="project",
    )
