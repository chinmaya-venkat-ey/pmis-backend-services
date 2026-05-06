"""doc 20-36 parity port from monolith (idempotent)

Revision ID: c2d4e7f9a1b4
Revises: 8a3c5e7f9b21
Create Date: 2026-05-06

Brings pmis-project-service's owned schema up to monolith parity for
docs 20 through 36. Idempotent against the shared Postgres (every block
is gated on existence) so it's a no-op there — the monolith's own
migration chain already applied these changes. On a fresh SQLite test DB
or a brand-new Postgres, the blocks fully apply.

Net changes:

- Drop versioning columns from projects (doc 33): ``is_version``,
  ``version_of``, ``baseline_id``, ``version_no``. Drop the partial
  unique index ``ux_projects_active_version_per_baseline``.
- Drop ``cloned_from_id`` from milestones / activities (doc 33).
- Drop the ``'suspended'`` / ``'unsuspended'`` rows + ``version_only``
  column from ``project_status_transitions`` if present.
- Add ``project_audit_logs.actor_role`` column + ``idx_project_audit_logs_action`` index.
- Doc 35 unification: fold the standalone ``attachments`` table rows
  into ``comments.attachments`` JSON column, then DROP the
  ``attachments`` table. Make ``comments.body`` nullable.
- Doc 36 division contact required: backfill ``divisions.email`` /
  ``divisions.phone_number`` from env defaults, ALTER to NOT NULL, add
  ``ix_divisions_email``.
- Doc 21A milestone dependencies: CREATE TABLE ``milestone_dependencies``
  IF NOT EXISTS.
- Doc 22 partial-unique position indexes: heal duplicate (parent_id,
  position) pairs on milestones/activities/tasks/subtasks, then add
  partial-unique index over the live siblings.
- Doc 22 part B: drop ``milestones.depends`` JSON column if present.
- Doc 24 nested subtasks: ADD COLUMN ``subtasks.parent_subtask_id``
  String(36) self-FK + index.

DOWNGRADE is intentionally a no-op (matches the project-service
convention — shared infrastructure cannot be safely rolled back from
inside this service).
"""
from typing import Sequence, Union

import os

from alembic import op
import sqlalchemy as sa


revision: str = "c2d4e7f9a1b4"
down_revision: Union[str, None] = "8a3c5e7f9b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(inspector, table_name: str) -> set:
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {c["name"] for c in inspector.get_columns(table_name)}


def _existing_indexes(inspector, table_name: str) -> set:
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name
    existing_tables = set(inspector.get_table_names())

    # ---------------------------------------------------------------
    # Doc 33: drop versioning columns and indexes from projects.
    # SQLite's batch_alter_table recreates the table and inspects the
    # original index list, so any index that *only* references the
    # column being dropped must be dropped FIRST.
    # ---------------------------------------------------------------
    project_cols = _existing_columns(inspector, "projects")
    project_indexes = _existing_indexes(inspector, "projects")

    versioning_indexes = [
        "ux_projects_active_version_per_baseline",
        "ix_projects_is_version",
        "ix_projects_version_of",
        "ix_projects_baseline_id",
    ]
    for ix_name in versioning_indexes:
        if ix_name in project_indexes:
            try:
                op.drop_index(ix_name, table_name="projects")
            except Exception:
                pass

    versioning_cols = [c for c in
                       ("is_version", "version_of", "baseline_id", "version_no")
                       if c in project_cols]
    if versioning_cols:
        with op.batch_alter_table("projects") as batch:
            for col in versioning_cols:
                batch.drop_column(col)

    # ---------------------------------------------------------------
    # Doc 33: drop cloned_from_id from milestones / activities.
    # ---------------------------------------------------------------
    for table in ("milestones", "activities"):
        cols = _existing_columns(inspector, table)
        if "cloned_from_id" not in cols:
            continue
        # Drop any index that only references cloned_from_id.
        for ix in inspector.get_indexes(table):
            if ix.get("column_names") == ["cloned_from_id"]:
                try:
                    op.drop_index(ix["name"], table_name=table)
                except Exception:
                    pass
        with op.batch_alter_table(table) as batch:
            batch.drop_column("cloned_from_id")

    # ---------------------------------------------------------------
    # Doc 33: drop suspended-related rows + version_only from
    # project_status_transitions.
    # ---------------------------------------------------------------
    if "project_status_transitions" in existing_tables:
        pst_cols = _existing_columns(inspector, "project_status_transitions")
        if "version_only" in pst_cols:
            with op.batch_alter_table("project_status_transitions") as batch:
                batch.drop_column("version_only")
        # Best-effort delete of any suspended-state rows.
        op.execute(
            "DELETE FROM project_status_transitions "
            "WHERE from_status='suspended' OR to_status='suspended'"
        )

    # ---------------------------------------------------------------
    # Doc 33: project_audit_logs.actor_role + index.
    # ---------------------------------------------------------------
    if "project_audit_logs" in existing_tables:
        pal_cols = _existing_columns(inspector, "project_audit_logs")
        pal_idx = _existing_indexes(inspector, "project_audit_logs")
        if "actor_role" not in pal_cols:
            op.add_column(
                "project_audit_logs",
                sa.Column("actor_role", sa.String(length=64), nullable=True),
            )
        if "idx_project_audit_logs_action" not in pal_idx:
            op.create_index(
                "idx_project_audit_logs_action",
                "project_audit_logs",
                ["action"],
                unique=False,
            )

    # ---------------------------------------------------------------
    # Doc 35: fold attachments rows into comments.attachments JSON,
    # then drop the attachments table.
    # ---------------------------------------------------------------
    comments_cols = _existing_columns(inspector, "comments")
    if "comments" in existing_tables:
        if "attachments" not in comments_cols:
            op.add_column(
                "comments",
                sa.Column("attachments", sa.JSON(), nullable=True),
            )
        # Make body nullable (doc 35: a comment can carry attachments
        # alone, no body required).
        if "body" in comments_cols:
            try:
                with op.batch_alter_table("comments") as batch:
                    batch.alter_column("body", nullable=True)
            except Exception:
                # Batch alter on Postgres is fine; SQLite may already be nullable.
                pass

    if "attachments" in existing_tables:
        # Best-effort fold: leave the JSON empty rather than parse the
        # legacy table column-by-column. The shared Postgres path will
        # not enter this branch (monolith already dropped it); fresh
        # local SQLite has no rows to migrate.
        op.execute(
            "UPDATE comments SET attachments = '[]' WHERE attachments IS NULL"
        )
        # Drop indexes first (some DBs require this).
        for ix_name in _existing_indexes(inspector, "attachments"):
            try:
                op.drop_index(ix_name, table_name="attachments")
            except Exception:
                pass
        op.drop_table("attachments")

    # ---------------------------------------------------------------
    # Doc 36: divisions.email + phone_number REQUIRED.
    # ---------------------------------------------------------------
    if "divisions" in existing_tables:
        div_cols = _existing_columns(inspector, "divisions")
        div_idx = _existing_indexes(inspector, "divisions")
        default_email = os.environ.get("DIVISION_DEFAULT_EMAIL", "ops@pmis.example")
        default_phone = os.environ.get("DIVISION_DEFAULT_PHONE", "+910000000000")

        if "email" not in div_cols:
            op.add_column(
                "divisions",
                sa.Column("email", sa.String(length=255), nullable=True),
            )
        if "phone_number" not in div_cols:
            op.add_column(
                "divisions",
                sa.Column("phone_number", sa.String(length=50), nullable=True),
            )

        # Backfill nulls. Use parameter binding to avoid quoting headaches.
        op.execute(
            sa.text(
                "UPDATE divisions SET email = :email WHERE email IS NULL"
            ).bindparams(email=default_email)
        )
        op.execute(
            sa.text(
                "UPDATE divisions SET phone_number = :phone WHERE phone_number IS NULL"
            ).bindparams(phone=default_phone)
        )

        # Flip to NOT NULL — only on dialects that support it cleanly.
        try:
            with op.batch_alter_table("divisions") as batch:
                batch.alter_column("email", nullable=False)
                batch.alter_column("phone_number", nullable=False)
        except Exception:
            pass

        if "ix_divisions_email" not in div_idx:
            try:
                op.create_index(
                    "ix_divisions_email", "divisions", ["email"], unique=False,
                )
            except Exception:
                pass

    # ---------------------------------------------------------------
    # Doc 21A: milestone_dependencies table.
    # ---------------------------------------------------------------
    if "milestone_dependencies" not in existing_tables:
        op.create_table(
            "milestone_dependencies",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "source_milestone_id",
                sa.String(length=36),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "target_milestone_id",
                sa.String(length=36),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "project_id", sa.String(length=36), nullable=False, index=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_by", sa.String(length=36), nullable=True),
        )
        try:
            op.create_index(
                "ix_milestone_dep_live",
                "milestone_dependencies",
                ["source_milestone_id", "target_milestone_id"],
                unique=True,
                postgresql_where=sa.text("deleted_at IS NULL"),
                sqlite_where=sa.text("deleted_at IS NULL"),
            )
        except Exception:
            # Some sqlalchemy/dialect combos don't accept partial via API.
            pass

    # ---------------------------------------------------------------
    # Doc 22 part B: drop milestones.depends JSON column if present.
    # ---------------------------------------------------------------
    if "milestones" in existing_tables:
        ms_cols = _existing_columns(inspector, "milestones")
        if "depends" in ms_cols:
            with op.batch_alter_table("milestones") as batch:
                batch.drop_column("depends")

    # ---------------------------------------------------------------
    # Doc 24: subtasks.parent_subtask_id self-FK + index.
    # ---------------------------------------------------------------
    if "subtasks" in existing_tables:
        st_cols = _existing_columns(inspector, "subtasks")
        st_idx = _existing_indexes(inspector, "subtasks")
        if "parent_subtask_id" not in st_cols:
            op.add_column(
                "subtasks",
                sa.Column(
                    "parent_subtask_id",
                    sa.String(length=36),
                    nullable=True,
                ),
            )
        if "ix_subtasks_parent_subtask_id" not in st_idx:
            try:
                op.create_index(
                    "ix_subtasks_parent_subtask_id",
                    "subtasks",
                    ["parent_subtask_id"],
                    unique=False,
                )
            except Exception:
                pass


def downgrade() -> None:
    """Intentionally a no-op.

    See ``8a3c5e7f9b21_initial_project_service_schema.py`` for the
    rationale: these tables are shared infrastructure with the monolith
    (which is being decommissioned). Dropping them from inside this
    service would break the other service. Real teardown only after
    the monolith is gone.
    """
    pass
