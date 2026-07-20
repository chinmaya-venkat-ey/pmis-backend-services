"""Phase A foundation — staffing plan + attendance + QGR config for NPQP.

Groundwork for computing NPQP (Net Planned Quarterly Payment) end-to-end:
NPQP = F + QGR, where F = Σ MP = Σ R × (1 − L/N) per resource per month
(RFP §5.25.2) and QGR is the Phase-1 Quarterly Guaranteed Revenue
(§5.23.2). Contract-management's SLA settlement service reads these tables
via a new NpqpService (Phase C).

New tables (all in ``project.*``, additive):

  * resource_deployment_plan   the missing staffing plan. One row per
                               resource per project, with monthly rate R
                               and deployment window. Feeds F for every
                               month the resource is active.
  * resource_attendance_month  one row per (resource, year, month) with
                               unpaid-leave count L. Nullable → assume
                               full presence. Two ``source`` values:
                               'manual' (form entry) and 'biometric'
                               (future import).
  * project_qgr_config         per (project, phase) QGR amount, applied
                               only to phases whose ``contract_phase_config
                               .qgr_eligible = true`` (Phase 1 for PMU;
                               empty for MSAP).

Revision ID: p1a000000029
Revises: p1a000000028
Create Date: 2026-07-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000029"
down_revision: str = "p1a000000028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. resource_deployment_plan ───────────────────────────────────
    op.create_table(
        "resource_deployment_plan",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("resource_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(120)),
        sa.Column("designation", sa.String(120)),
        # R in the RFP formula MP = R × (1 − L/N).
        sa.Column("monthly_rate", sa.Numeric(18, 2), nullable=False),
        sa.Column("deployment_start", sa.Date, nullable=False),
        sa.Column("deployment_end", sa.Date),
        # Which contract phase this resource is billed under — used by
        # the NpqpService to split F across phases when a project spans
        # more than one (e.g. PMU during Phase 1→2 transition).
        sa.Column("phase", sa.String(24)),
        # Free-text link back to the source-of-truth (activity_resources /
        # subtask_resources / task_resources — see the audit note in
        # PMIS-project-management/app/models/activity_resource.py). Kept
        # loose so we don't tie ourselves to one sidecar table.
        sa.Column("linked_resource_id", sa.String(36)),
        sa.Column("linked_resource_kind", sa.String(32)),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("notes", sa.Text),
        sa.Column("created_by", sa.String(36)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        schema="project",
    )
    op.create_index(
        "ix_rdp_project", "resource_deployment_plan", ["project_id"], schema="project",
    )
    op.create_index(
        "ix_rdp_project_status",
        "resource_deployment_plan", ["project_id", "status"],
        schema="project",
    )
    op.create_index(
        "ix_rdp_window",
        "resource_deployment_plan", ["deployment_start", "deployment_end"],
        schema="project",
    )

    # ── 2. resource_attendance_month ──────────────────────────────────
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
        sa.Column("month", sa.Integer, nullable=False),  # 1..12
        # L in the RFP formula. Nullable → not yet recorded.
        sa.Column("unpaid_leaves", sa.Numeric(6, 2)),
        # 'manual' | 'biometric'. Biometric import ships behind a feature
        # flag; manual entry is the day-1 fallback.
        sa.Column(
            "source", sa.String(16),
            nullable=False, server_default=sa.text("'manual'"),
        ),
        sa.Column("recorded_by", sa.String(36)),
        sa.Column("recorded_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "resource_deployment_id", "year", "month",
            name="uq_ram_resource_month",
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_ram_month_range"),
        schema="project",
    )
    op.create_index(
        "ix_ram_year_month",
        "resource_attendance_month", ["year", "month"],
        schema="project",
    )

    # ── 3. project_qgr_config ─────────────────────────────────────────
    # NOTE: `project_phase_qrg` (the legacy stub) is kept in place per the
    # additive-only migration principle — its ``qrg_applied`` flag is now
    # unused per its own model docstring but nothing depends on it being
    # dropped. A follow-up migration retires the stub once nothing reads
    # it (safest to defer).
    op.create_table(
        "project_qgr_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("phase", sa.String(24), nullable=False),  # 'PHASE_1' etc.
        # Amount per quarter — the RFP illustrates a flat QGR value for
        # Phase 1. If UIDAI later varies QGR quarter-over-quarter the
        # ``effective_from`` / ``effective_until`` window lets us stack
        # multiple rows without breaking the current-quarter lookup.
        sa.Column("qgr_amount_per_quarter", sa.Numeric(18, 2), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_until", sa.Date),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "project_id", "phase", "effective_from",
            name="uq_qgr_project_phase_from",
        ),
        schema="project",
    )
    op.create_index(
        "ix_qgr_project_phase",
        "project_qgr_config", ["project_id", "phase"],
        schema="project",
    )


def downgrade() -> None:
    op.drop_index("ix_qgr_project_phase", table_name="project_qgr_config", schema="project")
    op.drop_table("project_qgr_config", schema="project")

    op.drop_index("ix_ram_year_month", table_name="resource_attendance_month", schema="project")
    op.drop_table("resource_attendance_month", schema="project")

    op.drop_index("ix_rdp_window", table_name="resource_deployment_plan", schema="project")
    op.drop_index("ix_rdp_project_status", table_name="resource_deployment_plan", schema="project")
    op.drop_index("ix_rdp_project", table_name="resource_deployment_plan", schema="project")
    op.drop_table("resource_deployment_plan", schema="project")
