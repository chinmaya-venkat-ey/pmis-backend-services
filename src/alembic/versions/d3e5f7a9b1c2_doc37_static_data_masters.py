"""doc 37 part 1: static-data master catalogs

Revision ID: d3e5f7a9b1c2
Revises: c2d4e7f9a1b3
Create Date: 2026-05-06

Adds four small enum-like master tables that previously lived as
hardcoded tuples in code:

  project_categories   <- PROJECT_CATEGORY_CHOICES (services/transitions.py)
  activity_types       <- ACTIVITY_TYPES (domain/activities/activity.py)
  milestone_statuses   <- MILESTONE_STATUS_CHOICES (domain/milestones/milestone.py)
  activity_statuses    <- ACTIVITY_STATUS_CHOICES (domain/activities/activity.py)

Same shape across all four:
  id INTEGER PK, code VARCHAR(50) UNIQUE NOT NULL, label VARCHAR(255) NOT NULL,
  is_builtin BOOLEAN NOT NULL, active BOOLEAN NOT NULL,
  description VARCHAR(500) NULL, created_at, updated_at TIMESTAMP NOT NULL.

project_categories adds: requires_other BOOLEAN NOT NULL.
milestone_statuses + activity_statuses add: is_terminal BOOLEAN NOT NULL.

Each catalog gets a composite (active, code) index for the renderer-style
hot lookups + the base unique index on code.

Seed rows are inserted with is_builtin=true so they're protected from
the master-endpoint hard delete. Subsequent edits via PATCH are
preserved on every re-run; this loop only fills missing rows.

Idempotent (every step checks current state).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3e5f7a9b1c2"
# project-service's previous head is c2d4e7f9a1b4 (one digit off monolith's
# equivalent). Chain to that.
down_revision: Union[str, Sequence[str], None] = "c2d4e7f9a1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PROJECT_CATEGORY_SEED = (
    ("MSAP",   "MSAP",   False, "Mission-mode Software Application Programme."),
    ("MSIP",   "MSIP",   False, "Mission-mode Software Integration Programme."),
    ("BSP",    "BSP",    False, "Baseline Software Programme."),
    ("others", "Others", True,  "Free-text category — requires categoryOther + categoryOtherReason."),
)

_ACTIVITY_TYPE_SEED = (
    ("standard",      "Standard",      "Standard activity — has a status field."),
    ("resource",      "Resource",      "Resource activity — references resource_types."),
    ("transactional", "Transactional", "Transactional activity — no status / no resource block."),
)

_MS_STATUS_SEED = (
    ("not_completed", "Not completed", False, "Default state on milestone create."),
    ("completed",     "Completed",     True,  "Terminal — satisfies the dep-completion gate."),
)

_ACT_STATUS_SEED = (
    ("not_completed", "Not completed", False, "Default state on activity create."),
    ("completed",     "Completed",     True,  "Terminal — satisfies the dep-completion gate."),
)


def _has_table(inspector, name: str) -> bool:
    return name in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # ---- 1. project_categories ----
    if not _has_table(inspector, "project_categories"):
        op.create_table(
            "project_categories",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("requires_other", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "idx_project_categories_active_code",
            "project_categories",
            ["active", "code"],
            unique=False,
        )

    for code, label, requires_other, description in _PROJECT_CATEGORY_SEED:
        existing = bind.execute(
            sa.text("SELECT id FROM project_categories WHERE code = :code"),
            {"code": code},
        ).fetchone()
        if existing is None:
            bind.execute(
                sa.text(
                    "INSERT INTO project_categories "
                    "(code, label, is_builtin, requires_other, active, "
                    " description, created_at, updated_at) "
                    "VALUES (:code, :label, TRUE, :requires_other, TRUE, "
                    " :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "code": code, "label": label,
                    "requires_other": requires_other,
                    "description": description,
                },
            )

    # ---- 2. activity_types ----
    if not _has_table(inspector, "activity_types"):
        op.create_table(
            "activity_types",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "idx_activity_types_active_code",
            "activity_types",
            ["active", "code"],
            unique=False,
        )

    for code, label, description in _ACTIVITY_TYPE_SEED:
        existing = bind.execute(
            sa.text("SELECT id FROM activity_types WHERE code = :code"),
            {"code": code},
        ).fetchone()
        if existing is None:
            bind.execute(
                sa.text(
                    "INSERT INTO activity_types "
                    "(code, label, is_builtin, active, description, "
                    " created_at, updated_at) "
                    "VALUES (:code, :label, TRUE, TRUE, :description, "
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"code": code, "label": label, "description": description},
            )

    # ---- 3. milestone_statuses ----
    if not _has_table(inspector, "milestone_statuses"):
        op.create_table(
            "milestone_statuses",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "idx_milestone_statuses_active_code",
            "milestone_statuses",
            ["active", "code"],
            unique=False,
        )

    for code, label, is_terminal, description in _MS_STATUS_SEED:
        existing = bind.execute(
            sa.text("SELECT id FROM milestone_statuses WHERE code = :code"),
            {"code": code},
        ).fetchone()
        if existing is None:
            bind.execute(
                sa.text(
                    "INSERT INTO milestone_statuses "
                    "(code, label, is_builtin, is_terminal, active, "
                    " description, created_at, updated_at) "
                    "VALUES (:code, :label, TRUE, :is_terminal, TRUE, "
                    " :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "code": code, "label": label,
                    "is_terminal": is_terminal,
                    "description": description,
                },
            )

    # ---- 4. activity_statuses ----
    if not _has_table(inspector, "activity_statuses"):
        op.create_table(
            "activity_statuses",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "idx_activity_statuses_active_code",
            "activity_statuses",
            ["active", "code"],
            unique=False,
        )

    for code, label, is_terminal, description in _ACT_STATUS_SEED:
        existing = bind.execute(
            sa.text("SELECT id FROM activity_statuses WHERE code = :code"),
            {"code": code},
        ).fetchone()
        if existing is None:
            bind.execute(
                sa.text(
                    "INSERT INTO activity_statuses "
                    "(code, label, is_builtin, is_terminal, active, "
                    " description, created_at, updated_at) "
                    "VALUES (:code, :label, TRUE, :is_terminal, TRUE, "
                    " :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "code": code, "label": label,
                    "is_terminal": is_terminal,
                    "description": description,
                },
            )


def downgrade() -> None:
    """Drop the four catalogs. Existing rows in main tables that
    referenced the dropped values still resolve via the in-code
    fallback tuples — no data loss in domain tables.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for tbl in (
        "activity_statuses",
        "milestone_statuses",
        "activity_types",
        "project_categories",
    ):
        if _has_table(inspector, tbl):
            op.drop_table(tbl)
