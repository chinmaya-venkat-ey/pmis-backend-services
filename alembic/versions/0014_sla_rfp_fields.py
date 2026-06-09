"""Add RFP-native fields to sla_definitions.

Maps UIDAI RFP §5.28 SLA-table rows to first-class columns instead of
stuffing them into the ``metadata`` JSONB. The columns match the row
headers UIDAI uses in their SLA tables verbatim so the FE can show the
same shape the contract document does.

Columns added (all nullable — every existing SLA stays valid):

  * category               VARCHAR(50)
        User-facing grouping shown instead of formula_type. Examples:
        "Deliverable Submission", "Resource Management", "Governance Tool".
        formula_type stays on the table as the evaluator-dispatch key.

  * scope_text             TEXT
        Free text from RFP row "Scope of SLA". Example:
        "Applicable to all resources deployed by the Consultant".

  * data_source            VARCHAR(255)
        From RFP row "Process to capture raw data for SLA calculations".
        Example: "Manual — UIDAI biometric attendance system".

  * calculation_method     TEXT
        From RFP row "SLA calculation". Plain-English formula.

  * reports_submitted_to   VARCHAR(255)
        From RFP row "Reports and Data submitted to". Example:
        "Technology Management Division, UIDAI HO".

No data backfill — fresh installs / re-seeds populate these for PMU SLAs.
Old SLAs without values will render with a "—" in the FE.

Revision ID: 0014_sla_rfp_fields
Revises: 0013_widen_sla_columns
Create Date: 2026-06-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0014_sla_rfp_fields"
down_revision = "0013_widen_sla_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sla_definitions",
        sa.Column("category", sa.String(length=50), nullable=True),
        schema="contract",
    )
    op.add_column(
        "sla_definitions",
        sa.Column("scope_text", sa.Text(), nullable=True),
        schema="contract",
    )
    op.add_column(
        "sla_definitions",
        sa.Column("data_source", sa.String(length=255), nullable=True),
        schema="contract",
    )
    op.add_column(
        "sla_definitions",
        sa.Column("calculation_method", sa.Text(), nullable=True),
        schema="contract",
    )
    op.add_column(
        "sla_definitions",
        sa.Column("reports_submitted_to", sa.String(length=255), nullable=True),
        schema="contract",
    )
    op.create_index(
        "ix_sla_def_category",
        "sla_definitions", ["category"],
        schema="contract",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sla_def_category", table_name="sla_definitions", schema="contract",
    )
    for col in (
        "reports_submitted_to", "calculation_method",
        "data_source", "scope_text", "category",
    ):
        op.drop_column("sla_definitions", col, schema="contract")
