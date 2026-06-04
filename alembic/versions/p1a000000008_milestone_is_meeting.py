"""Add is_meeting flag + partial unique index to project.milestones.

Revision ID: p1a000000008
Revises: p1a000000007
Create Date: 2026-06-03

NOTE: Originally authored as ``p1a000000007`` but conflicted with the
parallel ``p1a000000007_payment_module`` migration that landed on
``EY-DIGIT/dev_micro`` on 2026-06-03. Renumbered to ``p1a000000008``
during the cross-repo merge so the chain stays linear. Body unchanged.

Adds a single boolean column ``is_meeting`` to ``project.milestones``
plus a partial unique index that enforces at most one live meeting
milestone per project.

Why:
  Per the 2026-06-03 product change, a published project owns a hidden
  "meeting" milestone — a container for meeting-type activities that
  should NOT appear in milestone lists, dashboards, critical path,
  discussion feed, or the approval inbox. The milestone is auto-created
  by the publish flow (and just-in-time by the project-detail controller
  for projects published before this change). The flag is the marker
  every downstream surface filters on.

Column:
  * ``is_meeting BOOLEAN NOT NULL DEFAULT FALSE`` — server default
    ``false`` so existing rows get the right value without backfill.

Index:
  * ``uq_milestones_one_meeting_per_project`` — partial UNIQUE on
    ``project_id`` where ``is_meeting = TRUE AND deleted_at IS NULL``.
    Guarantees at most one live meeting milestone per project; soft-
    deleting one (rare; mutation is normally blocked) frees the slot.

Per A19 (alembic conventions, PERMISSIONS_TEAM_DECISIONS.md §7.1) a
real downgrade is implemented: drop the index, drop the column.

Revision id is intentionally kept short (12 chars) to comfortably fit
under alembic's default 32-char ``version_num`` column.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000008"
down_revision: str = "p1a000000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "milestones",
        sa.Column(
            "is_meeting",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="project",
    )
    # Partial unique index — only enforced on live meeting rows so the
    # normal (project_id, position) constraints aren't disturbed.
    op.execute("""
        CREATE UNIQUE INDEX uq_milestones_one_meeting_per_project
        ON project.milestones (project_id)
        WHERE is_meeting = TRUE AND deleted_at IS NULL
    """)


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS project.uq_milestones_one_meeting_per_project"
    )
    op.drop_column("milestones", "is_meeting", schema="project")
