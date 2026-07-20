"""Drop the two duplicate project.* tables now that leave-mgmt is
confirmed to own the same data.

Rationale (research 2026-07-20):
  * ``project.resource_deployment_plan`` — 100% duplicate of
    ``leave.master_resource`` (identity) + ``leave.project_resource``
    (which is richer — has ``rate_card_by_year`` JSONB supporting
    multi-year escalation, not just a single monthly_rate). Deployed
    leave-management service exposes the same data via
    ``GET /leaves/api/resources`` and ``.../rate-cards``.
  * ``project.resource_attendance_month`` — 100% duplicate of
    ``leave.attendance`` (daily grain, 253 rows of live data on VM as
    of 2026-07-20). Deployed leave-management service exposes it via
    ``GET /leaves/api/attendance/report/*`` and computes derived
    quarterly settlement (RFP §5.24.1) via
    ``GET /leaves/api/attendance/quarterly-leave``.

Both tables are empty on the VM (0 rows) — dropping them is safe.

``project.project_qgr_config`` is KEPT — QGR (RFP §5.23.2) is a UIDAI
contract concept, not attendance, and leave-management has no
equivalent. Phase C's NpqpService will read QGR from here and pull
F (staff cost) from leave-management via HTTP.

Revision ID: p1a000000030
Revises: p1a000000029
Create Date: 2026-07-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000030"
down_revision: str = "p1a000000029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop resource_attendance_month first (it FKs resource_deployment_plan).
    op.drop_index("ix_ram_year_month", table_name="resource_attendance_month", schema="project")
    op.drop_table("resource_attendance_month", schema="project")

    op.drop_index("ix_rdp_window", table_name="resource_deployment_plan", schema="project")
    op.drop_index("ix_rdp_project_status", table_name="resource_deployment_plan", schema="project")
    op.drop_index("ix_rdp_project", table_name="resource_deployment_plan", schema="project")
    op.drop_table("resource_deployment_plan", schema="project")


def downgrade() -> None:
    # Recreate both tables verbatim from p1a000000029 so this migration
    # is reversible. If leave-mgmt integration turns out to be wrong
    # somehow, `alembic downgrade -1` restores the empty tables.
    op.create_table(
        "resource_deployment_plan",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("resource_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(120)),
        sa.Column("designation", sa.String(120)),
        sa.Column("monthly_rate", sa.Numeric(18, 2), nullable=False),
        sa.Column("deployment_start", sa.Date, nullable=False),
        sa.Column("deployment_end", sa.Date),
        sa.Column("phase", sa.String(24)),
        sa.Column("linked_resource_id", sa.String(36)),
        sa.Column("linked_resource_kind", sa.String(32)),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("notes", sa.Text),
        sa.Column("created_by", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        schema="project",
    )
    op.create_index("ix_rdp_project", "resource_deployment_plan", ["project_id"], schema="project")
    op.create_index("ix_rdp_project_status", "resource_deployment_plan",
                    ["project_id", "status"], schema="project")
    op.create_index("ix_rdp_window", "resource_deployment_plan",
                    ["deployment_start", "deployment_end"], schema="project")

    op.create_table(
        "resource_attendance_month",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "resource_deployment_id", sa.String(36),
            sa.ForeignKey(
                "project.resource_deployment_plan.id",
                ondelete="CASCADE",
                name="fk_ram_deployment",
            ),
            nullable=False,
        ),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("unpaid_leaves", sa.Numeric(6, 2)),
        sa.Column("source", sa.String(16), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("recorded_by", sa.String(36)),
        sa.Column("recorded_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("resource_deployment_id", "year", "month",
                            name="uq_ram_resource_month"),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_ram_month_range"),
        schema="project",
    )
    op.create_index("ix_ram_year_month", "resource_attendance_month",
                    ["year", "month"], schema="project")
