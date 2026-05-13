"""Doc 47 follow-up: add actor_code to project_audit_logs.

Revision ID: c3a8d1f7e542
Revises: b1d3e7a9c204
Create Date: 2026-05-12

Mirror of monolith migration c3a8d1f7e542. Mirrors ``users.user_code``
(e.g. ``US-CHIN-260506120444``) onto the audit row at write time.
NOT NULL with a ``'system'`` fallback for rows whose actor_id is null
or whose user row was deleted.
"""
from alembic import op
import sqlalchemy as sa


revision = "c3a8d1f7e542"
down_revision = "b1d3e7a9c204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: monolith ships an identical revision (same ID, same
    # DDL) and runs against the same shared DB via its own alembic
    # version table. Skip the ADD if another service got here first.
    bind = op.get_bind()
    existing = {
        c["name"] for c in sa.inspect(bind).get_columns("project_audit_logs")
    }
    if "actor_code" not in existing:
        op.add_column(
            "project_audit_logs",
            sa.Column("actor_code", sa.String(length=40), nullable=True),
        )
    # Backfill from the users table — safe to re-run; WHERE filters
    # narrow to rows that need it.
    op.execute(
        "UPDATE project_audit_logs "
        "SET actor_code = ("
        "    SELECT user_code FROM users WHERE users.id = project_audit_logs.actor_id"
        ") "
        "WHERE actor_id IS NOT NULL AND actor_code IS NULL"
    )
    op.execute(
        "UPDATE project_audit_logs SET actor_code = 'system' "
        "WHERE actor_code IS NULL"
    )
    # SET NOT NULL is a no-op when the column is already NOT NULL.
    op.alter_column(
        "project_audit_logs", "actor_code",
        existing_type=sa.String(length=40), nullable=False,
    )


def downgrade() -> None:
    op.drop_column("project_audit_logs", "actor_code")
