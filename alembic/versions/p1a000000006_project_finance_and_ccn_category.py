"""Add project finance fields and milestone/activity CCN category.

Revision ID: p1a000000006
Revises: p1a000000005
Create Date: 2026-06-01

Why:
  Project-level finance fields drive the CCN cap calculation:
    - ``total_project_value_excl_tax`` — contract base value (in INR rupees,
      stored as NUMERIC(18, 2)).
    - ``tax_percent`` — tax rate applied for derived inclusive-tax display
      (stored as NUMERIC(5, 2)). The inclusive-tax value is computed on
      response, not stored.
    - ``ccn_cap_percent`` — % cap up to which the project value may be
      extended through CCN-categorized milestones/activities (default 25%).

  Milestone- and activity-level category + CCN value:
    - ``category`` ∈ ('original', 'asg', 'ccn').
      - Pre-publish creates of M/A are always 'original' (server forces it).
      - Post-publish creates may be 'asg' (no money impact) or 'ccn'
        (carries a ccn_value contributing to project-level CCN consumption).
    - ``ccn_value`` — monetary value (INR, NUMERIC(18, 2)). Required > 0
      when category='ccn', 0 otherwise (enforced at service layer + DB
      CHECK constraint).

  Safe defaults + nullable backfill ensure existing rows continue to
  read/write fine. TPV defaults to 0 — a project may publish with TPV=0,
  in which case the CCN cap check is skipped (finance dormant). Setting
  TPV > 0 activates the cap.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000006"
down_revision: str = "p1a000000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------- project.projects --------
    with op.batch_alter_table("projects", schema="project") as batch:
        batch.add_column(
            sa.Column(
                "total_project_value_excl_tax",
                sa.Numeric(18, 2),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.add_column(
            sa.Column(
                "tax_percent",
                sa.Numeric(5, 2),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.add_column(
            sa.Column(
                "ccn_cap_percent",
                sa.Numeric(5, 2),
                nullable=False,
                server_default=sa.text("25"),
            )
        )

    # -------- project.milestones --------
    with op.batch_alter_table("milestones", schema="project") as batch:
        batch.add_column(
            sa.Column(
                "category",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'original'"),
            )
        )
        batch.add_column(
            sa.Column(
                "ccn_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    # -------- project.activities --------
    with op.batch_alter_table("activities", schema="project") as batch:
        batch.add_column(
            sa.Column(
                "category",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'original'"),
            )
        )
        batch.add_column(
            sa.Column(
                "ccn_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    # -------- DB CHECK constraints --------
    op.create_check_constraint(
        "ck_projects_tpv_excl_tax_nonneg",
        "projects",
        "total_project_value_excl_tax >= 0",
        schema="project",
    )
    op.create_check_constraint(
        "ck_projects_tax_percent_range",
        "projects",
        "tax_percent >= 0 AND tax_percent <= 100",
        schema="project",
    )
    op.create_check_constraint(
        "ck_projects_ccn_cap_percent_range",
        "projects",
        "ccn_cap_percent >= 0 AND ccn_cap_percent <= 100",
        schema="project",
    )

    op.create_check_constraint(
        "ck_milestones_category",
        "milestones",
        "category IN ('original', 'asg', 'ccn')",
        schema="project",
    )
    op.create_check_constraint(
        "ck_milestones_ccn_value_nonneg",
        "milestones",
        "ccn_value >= 0",
        schema="project",
    )
    op.create_check_constraint(
        "ck_milestones_ccn_value_requires_ccn",
        "milestones",
        "category = 'ccn' OR ccn_value = 0",
        schema="project",
    )

    op.create_check_constraint(
        "ck_activities_category",
        "activities",
        "category IN ('original', 'asg', 'ccn')",
        schema="project",
    )
    op.create_check_constraint(
        "ck_activities_ccn_value_nonneg",
        "activities",
        "ccn_value >= 0",
        schema="project",
    )
    op.create_check_constraint(
        "ck_activities_ccn_value_requires_ccn",
        "activities",
        "category = 'ccn' OR ccn_value = 0",
        schema="project",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_activities_ccn_value_requires_ccn", "activities",
        schema="project", type_="check",
    )
    op.drop_constraint(
        "ck_activities_ccn_value_nonneg", "activities",
        schema="project", type_="check",
    )
    op.drop_constraint(
        "ck_activities_category", "activities",
        schema="project", type_="check",
    )

    op.drop_constraint(
        "ck_milestones_ccn_value_requires_ccn", "milestones",
        schema="project", type_="check",
    )
    op.drop_constraint(
        "ck_milestones_ccn_value_nonneg", "milestones",
        schema="project", type_="check",
    )
    op.drop_constraint(
        "ck_milestones_category", "milestones",
        schema="project", type_="check",
    )

    op.drop_constraint(
        "ck_projects_ccn_cap_percent_range", "projects",
        schema="project", type_="check",
    )
    op.drop_constraint(
        "ck_projects_tax_percent_range", "projects",
        schema="project", type_="check",
    )
    op.drop_constraint(
        "ck_projects_tpv_excl_tax_nonneg", "projects",
        schema="project", type_="check",
    )

    with op.batch_alter_table("activities", schema="project") as batch:
        batch.drop_column("ccn_value")
        batch.drop_column("category")

    with op.batch_alter_table("milestones", schema="project") as batch:
        batch.drop_column("ccn_value")
        batch.drop_column("category")

    with op.batch_alter_table("projects", schema="project") as batch:
        batch.drop_column("ccn_cap_percent")
        batch.drop_column("tax_percent")
        batch.drop_column("total_project_value_excl_tax")
