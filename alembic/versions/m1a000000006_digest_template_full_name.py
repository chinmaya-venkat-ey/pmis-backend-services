"""Switch the deadline-digest email template placeholder to {full_name}.

Revision ID: m1a000000006
Revises: m1a000000005
Create Date: 2026-06-05

Why:
  The app dropped the first_name/last_name split — display names are now a
  single ``full_name`` everywhere. The built-in ``project_deadline_digest``
  template, seeded by m1a000000002, still carried a ``{first_name}``
  placeholder. notification-svc keeps supplying ``first_name`` as a
  back-compat alias so prod kept rendering correctly, but the canonical key
  is ``full_name``; this aligns the already-seeded row with the fresh-seed
  template so the alias can eventually go away.

  Idempotent + targeted: only rewrites the one built-in row, and only when
  it still holds the old placeholder, so re-runs and hand-edited rows are
  left untouched.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "m1a000000006"
down_revision = "m1a000000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # REPLACE is a no-op when the placeholder is absent, so no LIKE guard is
    # needed (and a LIKE '%...%' would clash with psycopg2's %-paramstyle).
    op.execute(sa.text("""
        UPDATE masters.notification_templates
           SET body = REPLACE(body, '{first_name}', '{full_name}')
         WHERE template_kind = 'project_deadline_digest'
           AND is_builtin = true
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE masters.notification_templates
           SET body = REPLACE(body, '{full_name}', '{first_name}')
         WHERE template_kind = 'project_deadline_digest'
           AND is_builtin = true
    """))
