"""Doc 47 audit-log enrichment: add NOT NULL denormalized columns.

Revision ID: b1d3e7a9c204
Revises: d2c4f1a9b8e7
Create Date: 2026-05-12

Mirror of monolith migration b1d3e7a9c204. The ``project_audit_logs``
table previously carried only the foreign-key references
(``project_id``, ``actor_id``) and the action / before / after
payload. Doc 47 enriches it with snapshotted, NOT-NULL columns so
audit rows stay meaningful when source rows later mutate:

  * actor_login    — varchar(50)   — username at write time
  * project_name   — varchar(255)  — project name at write time
  * project_status — varchar(50)   — project status at write time
  * owner          — varchar(50)   — project owner at write time

It also flips ``actor_role`` from NULLABLE to NOT NULL — every audit row
must identify which role bucket the actor occupied.

Backfill uses correlated subqueries (works on both Postgres + SQLite);
unresolvable values land as ``'system'`` (for actor_login / actor_role)
or ``'(unknown)'`` (for the project snapshot columns) so the eventual
NOT NULL constraint can be applied without rejecting legacy rows.
"""
from alembic import op
import sqlalchemy as sa


revision = "b1d3e7a9c204"
down_revision = "d2c4f1a9b8e7"
branch_labels = None
depends_on = None


_NEW_COLS = ("actor_login", "project_name", "project_status", "owner")


def _existing_columns(table: str) -> set:
    """Names of columns currently present on ``table``.

    Used to make the upgrade idempotent: monolith ships an identical
    revision (same ID, same DDL) and runs against the same shared DB
    via its own alembic version table. Whichever service runs alembic
    first applies the columns; the other service must skip the ADDs
    on its own pass to avoid "column already exists" errors.
    """
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _existing_indexes(table: str) -> set:
    bind = op.get_bind()
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    existing = _existing_columns("project_audit_logs")

    # 1) Add columns as nullable so backfill doesn't get rejected.
    #    Skip any that another service has already added.
    if "actor_login" not in existing:
        op.add_column(
            "project_audit_logs",
            sa.Column("actor_login", sa.String(length=50), nullable=True),
        )
    if "project_name" not in existing:
        op.add_column(
            "project_audit_logs",
            sa.Column("project_name", sa.String(length=255), nullable=True),
        )
    if "project_status" not in existing:
        op.add_column(
            "project_audit_logs",
            sa.Column("project_status", sa.String(length=50), nullable=True),
        )
    if "owner" not in existing:
        op.add_column(
            "project_audit_logs",
            sa.Column("owner", sa.String(length=50), nullable=True),
        )

    # 2) Backfill from joins. Correlated subqueries work on both
    #    Postgres and SQLite without dialect branching.
    op.execute(
        "UPDATE project_audit_logs "
        "SET project_name = ("
        "    SELECT name FROM projects WHERE projects.id = project_audit_logs.project_id"
        "), "
        "project_status = ("
        "    SELECT status FROM projects WHERE projects.id = project_audit_logs.project_id"
        "), "
        "owner = ("
        "    SELECT owner FROM projects WHERE projects.id = project_audit_logs.project_id"
        ")"
    )
    op.execute(
        "UPDATE project_audit_logs "
        "SET actor_login = ("
        "    SELECT login FROM users WHERE users.id = project_audit_logs.actor_id"
        ") "
        "WHERE actor_id IS NOT NULL"
    )

    # 3) Catch-all defaults for rows whose source FK was deleted or
    #    where actor_id is NULL (system-initiated actions).
    op.execute(
        "UPDATE project_audit_logs SET actor_login = 'system' "
        "WHERE actor_login IS NULL"
    )
    op.execute(
        "UPDATE project_audit_logs SET project_name = '(unknown)' "
        "WHERE project_name IS NULL"
    )
    op.execute(
        "UPDATE project_audit_logs SET project_status = '(unknown)' "
        "WHERE project_status IS NULL"
    )
    op.execute(
        "UPDATE project_audit_logs SET owner = '(unknown)' "
        "WHERE owner IS NULL"
    )
    op.execute(
        "UPDATE project_audit_logs SET actor_role = 'system' "
        "WHERE actor_role IS NULL"
    )

    # 4) Set NOT NULL constraints on all five columns.
    op.alter_column(
        "project_audit_logs", "actor_login",
        existing_type=sa.String(length=50), nullable=False,
    )
    op.alter_column(
        "project_audit_logs", "project_name",
        existing_type=sa.String(length=255), nullable=False,
    )
    op.alter_column(
        "project_audit_logs", "project_status",
        existing_type=sa.String(length=50), nullable=False,
    )
    op.alter_column(
        "project_audit_logs", "owner",
        existing_type=sa.String(length=50), nullable=False,
    )
    op.alter_column(
        "project_audit_logs", "actor_role",
        existing_type=sa.String(length=50), nullable=False,
    )

    # 5) Index on actor_login to keep "filter by user" reads fast.
    #    Skip if monolith's mirror already created it on the shared DB.
    if "idx_project_audit_logs_actor_login" not in _existing_indexes(
        "project_audit_logs",
    ):
        op.create_index(
            "idx_project_audit_logs_actor_login",
            "project_audit_logs", ["actor_login"],
        )


def downgrade() -> None:
    op.drop_index(
        "idx_project_audit_logs_actor_login",
        table_name="project_audit_logs",
    )
    op.alter_column(
        "project_audit_logs", "actor_role",
        existing_type=sa.String(length=50), nullable=True,
    )
    for col in _NEW_COLS:
        op.drop_column("project_audit_logs", col)
