"""Phase 2: Add master tables — severity_master, contract_type_master, data_field_master.

severity_master     : Per-project severity level definitions (level 0-4, points, label).
                      Rows are created via API when a project LD config is onboarded;
                      not seeded here because they are project-specific.
contract_type_master: System-wide contract types (BSP, MSAP, PMU, MSIP, GRCP). Seeded here.
data_field_master   : System-wide observable variable catalog for the SLA condition builder.
                      Seeded with fields covering MSAP SLAs 001-027 and common BSP/PMU/MSIP patterns.

Revision ID: 0005_master_tables
Revises: 0004_project_ld_refactor
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_master_tables"
down_revision = "0004_project_ld_refactor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. severity_master — per-project severity level definitions
    #    project_id is a soft FK to project_ld_config.project_id (same schema,
    #    but we use a soft reference so the table can be read without a join).
    # -----------------------------------------------------------------------
    op.create_table(
        "severity_master",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),          # 0-4
        sa.Column("points", sa.Integer, nullable=False),         # negative allowed (level 0)
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("project_id", "level", name="uq_sev_master_project_level"),
        schema="contract",
    )
    op.create_index(
        "ix_sev_master_project_id", "severity_master", ["project_id"], schema="contract"
    )

    # -----------------------------------------------------------------------
    # 2. contract_type_master — system-wide contract type reference
    # -----------------------------------------------------------------------
    op.create_table(
        "contract_type_master",
        sa.Column("code", sa.String(20), primary_key=True),   # BSP, MSAP, …
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        schema="contract",
    )
    op.execute(
        """
        INSERT INTO contract.contract_type_master (code, display_name, description) VALUES
        ('BSP',  'Business Support Package',
                 'HR payroll, logistics, helpdesk and administrative support services'),
        ('MSAP', 'Managed Service Application Package',
                 'Application development, maintenance and operations'),
        ('PMU',  'Project Management Unit',
                 'Programme-level monitoring, coordination and reporting'),
        ('MSIP', 'Managed Service Infrastructure Package',
                 'IT infrastructure management and operations'),
        ('GRCP', 'Government Rate Contract Package',
                 'Items procured under government rate contracts')
        """
    )

    # -----------------------------------------------------------------------
    # 3. data_field_master — observable variable catalog (SLA condition builder)
    #
    #    field_name    : internal snake_case key used in DSL / condition expressions
    #    display_name  : human-readable label shown to the admin in the form
    #    data_type     : INTEGER | DECIMAL | DATE | BOOLEAN
    #    unit          : %, days, hours, count, score, ms, INR
    #    example_value : UI hint for the "Try Now" panel
    #    applicable_to : NULL means applies to ALL contract types;
    #                    non-NULL restricts the field to listed codes
    # -----------------------------------------------------------------------
    op.create_table(
        "data_field_master",
        sa.Column("field_name", sa.String(100), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("data_type", sa.String(20), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("example_value", sa.String(50)),
        sa.Column("applicable_to", postgresql.ARRAY(sa.String(20))),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        schema="contract",
    )
    # Covers MSAP SLA 001-027 and common patterns across BSP / PMU / MSIP / GRCP
    op.execute(
        """
        INSERT INTO contract.data_field_master
            (field_name, display_name, data_type, unit, example_value, applicable_to)
        VALUES
        -- Deadline / timeline fields (SLA 001-013 transition, general milestones)
        ('days_variance',
         'Days Delayed (from planned date)',
         'INTEGER', 'days', '7',
         ARRAY['MSAP','PMU','BSP']),

        ('milestone_delay_days',
         'Milestone Delay (days)',
         'INTEGER', 'days', '3',
         ARRAY['MSAP','PMU']),

        ('deliverable_delay_days',
         'Deliverable Delay (days)',
         'INTEGER', 'days', '5',
         ARRAY['MSAP','PMU']),

        -- Availability / uptime (SLA 014 uptime, MSIP infra)
        ('uptime_pct',
         'System Uptime %',
         'DECIMAL', '%', '99.5',
         ARRAY['MSAP','MSIP']),

        ('availability_pct',
         'Service Availability %',
         'DECIMAL', '%', '99.0',
         ARRAY['MSAP','MSIP']),

        -- Code quality / defects (SLA 015, SLA 016 WAC)
        ('defect_wac',
         'Defect WAC Score',
         'DECIMAL', 'score', '0.12',
         ARRAY['MSAP']),

        ('defect_count',
         'Defect Count',
         'INTEGER', 'count', '15',
         ARRAY['MSAP','PMU']),

        ('code_coverage_pct',
         'Code Coverage %',
         'DECIMAL', '%', '82.0',
         ARRAY['MSAP']),

        -- Resource management (SLA 020-024)
        ('resource_replacement_count',
         'Resource Replacements (count)',
         'INTEGER', 'count', '1',
         ARRAY['MSAP','BSP','PMU']),

        ('headcount',
         'Headcount On Site',
         'INTEGER', 'count', '50',
         ARRAY['MSAP','BSP','PMU','MSIP']),

        ('resource_skill_score',
         'Resource Skill Score',
         'DECIMAL', 'score', '3.5',
         ARRAY['MSAP','BSP','PMU']),

        ('training_compliance_pct',
         'Training Compliance %',
         'DECIMAL', '%', '90.0',
         ARRAY['MSAP','BSP','PMU']),

        -- TAT / response (SLA 025-027 operations, helpdesk)
        ('tat_days',
         'Turnaround Time (Days)',
         'INTEGER', 'days', '2',
         NULL),

        ('tat_hours',
         'Turnaround Time (Hours)',
         'INTEGER', 'hours', '4',
         NULL),

        ('sla_breach_count',
         'SLA Breach Count',
         'INTEGER', 'count', '2',
         NULL),

        -- Infrastructure / security (MSIP)
        ('patch_compliance_pct',
         'Patch Compliance %',
         'DECIMAL', '%', '95.0',
         ARRAY['MSAP','MSIP']),

        ('incident_count',
         'Incident Count',
         'INTEGER', 'count', '3',
         ARRAY['MSAP','MSIP']),

        ('dr_rto_hours',
         'DR Recovery Time Objective (Hours)',
         'INTEGER', 'hours', '4',
         ARRAY['MSAP','MSIP']),

        ('response_time_ms',
         'Response Time (milliseconds)',
         'INTEGER', 'ms', '800',
         ARRAY['MSAP','MSIP']),

        -- Helpdesk / operations (BSP, MSIP)
        ('ticket_resolution_pct',
         'Ticket Resolution Rate %',
         'DECIMAL', '%', '92.0',
         ARRAY['BSP','MSIP']),

        ('change_success_rate_pct',
         'Change Success Rate %',
         'DECIMAL', '%', '98.0',
         ARRAY['MSAP','MSIP']),

        ('backup_success_pct',
         'Backup Success Rate %',
         'DECIMAL', '%', '99.5',
         ARRAY['MSIP'])
        """
    )


def downgrade() -> None:
    op.drop_table("data_field_master", schema="contract")
    op.drop_table("contract_type_master", schema="contract")
    op.drop_index(
        "ix_sev_master_project_id", table_name="severity_master", schema="contract"
    )
    op.drop_table("severity_master", schema="contract")
