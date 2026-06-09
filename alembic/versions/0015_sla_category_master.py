"""Add contract.sla_category_master — user-facing SLA category catalog.

Replaces the front-end's hardcoded category-to-engine map with a typed,
seeded reference table. The FE fetches the list, the BE owns the truth.

Columns:
  * code          VARCHAR(50)  PK   slug used by the FE (e.g. "DELIVERABLE_SUBMISSION")
  * display_name  VARCHAR(100)      what the user sees (e.g. "Deliverable Submission")
  * formula_type  VARCHAR(30)       evaluator dispatch key — point_accumulation /
                                    fixed_escalation / band_accumulation / wac
  * description   TEXT              one-line description shown as a hint
  * sort_order    INTEGER           presentation order on the picker
  * is_active     BOOLEAN           soft-disable to hide from the picker

The seeded baseline mirrors what the FE was hardcoding before, plus rationale:

  | code                    | display_name            | engine             |
  |-------------------------|-------------------------|--------------------|
  | DELIVERABLE_SUBMISSION  | Deliverable Submission  | fixed_escalation   |
  | QUERY_RESOLUTION        | Query Resolution        | fixed_escalation   |
  | RECOMMENDATION_QUALITY  | Recommendation Quality  | point_accumulation |
  | RESOURCE_MANAGEMENT     | Resource Management     | point_accumulation |
  | GOVERNANCE_TOOL         | Governance Tool         | point_accumulation |

Adding a new category here makes it available on the FE picker on the next
page-load — no FE deploy required.

Revision ID: 0015_sla_category_master
Revises: 0014_sla_rfp_fields
Create Date: 2026-06-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_sla_category_master"
down_revision = "0014_sla_rfp_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sla_category_master",
        sa.Column("code", sa.String(50), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column(
            "formula_type", sa.String(30), nullable=False,
            comment="Internal evaluator key — see app/services/sla_evaluator/.",
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="100"),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "formula_type IN ('point_accumulation','fixed_escalation','band_accumulation','wac')",
            name="ck_sla_category_formula_type",
        ),
        schema="contract",
    )
    op.create_index(
        "ix_sla_category_master_sort_order",
        "sla_category_master", ["sort_order"],
        schema="contract",
    )

    # Seed the five PMU-derived categories.
    op.execute("""
        INSERT INTO contract.sla_category_master
            (code, display_name, formula_type, description, sort_order)
        VALUES
        ('DELIVERABLE_SUBMISSION', 'Deliverable Submission', 'fixed_escalation',
         'LD escalates linearly per unit time (e.g. 0.5% per week) applied on deliverable cost. RFP §5.28.2.',
         10),
        ('QUERY_RESOLUTION',       'Query Resolution',       'fixed_escalation',
         'LD escalates per day of delay past a grace period, applied on NPQP. RFP §5.28.3.a.',
         20),
        ('RECOMMENDATION_QUALITY', 'Recommendation Quality', 'point_accumulation',
         'Severity assigned by count of incorrect recommendations per quarter. RFP §5.28.3.b.',
         30),
        ('RESOURCE_MANAGEMENT',    'Resource Management',    'point_accumulation',
         'Severity by resource replacement count, KT overlap days, availability, onboarding variance, etc. RFP §5.28.3.c-g.',
         40),
        ('GOVERNANCE_TOOL',        'Governance Tool',        'point_accumulation',
         'Severity by deployment delay or count of failures. RFP §5.28.4.',
         50)
    """)


def downgrade() -> None:
    op.drop_index(
        "ix_sla_category_master_sort_order",
        table_name="sla_category_master", schema="contract",
    )
    op.drop_table("sla_category_master", schema="contract")
