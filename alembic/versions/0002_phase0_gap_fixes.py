"""Phase 0 gap fixes — G17, G19, G20, G21.

G17: guard_group_id on sla_guard_conditions (AND-grouped guard evaluation)
G19: band_group_id on sla_condition_bands (compound 2D band evaluation)
G20: linear penalty params in fixed_escalation formula_library seed row (JSONB update only)
G21: ld_computation_base on sla_definitions (controls INR payment base for LD computation)

Revision ID: 0002_phase0_gaps
Revises: 0001_phase1
Create Date: 2026-05-26
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0002_phase0_gaps"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# G20 — updated fixed_escalation parameter_schema with linear penalty params
# ---------------------------------------------------------------------------

_FIXED_ESCALATION_SCHEMA_V2 = {
    "type": "object",
    "required": ["period_unit"],
    "properties": {
        "period_unit": {
            "type": "string",
            "enum": ["MONTH", "QUARTER", "YEAR", "ONE_TIME"],
        },
        "milestone_type": {
            "type": "string",
            "enum": ["DATE", "NUMERIC", "DELAY_DAYS"],
        },
        "cap_percent": {"type": "number", "minimum": 0},
        # G20 — linear penalty extension ----------------------------------------
        # Formula: ld_percent = base_ld_from_lookup +
        #          additional_rate_per_unit × max(0, delay_units - additional_rate_grace_units)
        # Pure-linear case (PMU SLA 001/002): omit lookup table, set additional_rate_per_unit only.
        "additional_rate_per_unit": {
            "type": "number",
            "description": (
                "Linear LD increment per unit beyond the grace period (e.g. 0.1 for 0.1%/day). "
                "For pure-linear penalty with no lookup tiers (PMU SLA 001/002 — 0.5%/week of "
                "deliverable cost), set this alone without a lookup table."
            ),
        },
        "additional_rate_unit": {
            "type": "string",
            "enum": ["DAY", "WEEK", "MONTH"],
            "description": "Unit for the linear rate (DAY for BSP/MSIP; WEEK for PMU SLA 001/002).",
        },
        "additional_rate_grace_units": {
            "type": "integer",
            "default": 0,
            "description": (
                "Units of delay after which the linear rate begins accruing. "
                "BSP SLA 013: 5 working days. PMU SLA 001/002/003: 0 (no grace). "
                "MSIP SLA 43: 0."
            ),
        },
    },
}


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # G17 — add guard_group_id to sla_guard_conditions
    # -----------------------------------------------------------------------
    op.add_column(
        "sla_guard_conditions",
        sa.Column("guard_group_id", sa.Integer, nullable=True),
        schema="contract",
    )

    # -----------------------------------------------------------------------
    # G19 — add band_group_id to sla_condition_bands
    # -----------------------------------------------------------------------
    op.add_column(
        "sla_condition_bands",
        sa.Column("band_group_id", sa.Integer, nullable=True),
        schema="contract",
    )

    # -----------------------------------------------------------------------
    # G21 — add ld_computation_base to sla_definitions
    # -----------------------------------------------------------------------
    op.add_column(
        "sla_definitions",
        sa.Column(
            "ld_computation_base",
            sa.String(30),
            nullable=False,
            server_default="QUARTERLY_PAYMENT",
        ),
        schema="contract",
    )

    # -----------------------------------------------------------------------
    # G20 — update fixed_escalation parameter_schema in formula_library
    # This is a data patch only (no DDL change) — updates the JSONB seed row.
    # -----------------------------------------------------------------------
    op.execute(
        sa.text(
            "UPDATE contract.formula_library "
            "SET parameter_schema = CAST(:schema AS jsonb) "
            "WHERE formula_type = 'fixed_escalation'"
        ).bindparams(schema=json.dumps(_FIXED_ESCALATION_SCHEMA_V2))
    )


def downgrade() -> None:
    # Revert G20 — restore original fixed_escalation schema (without linear penalty params)
    _original_schema = {
        "type": "object",
        "required": ["period_unit"],
        "properties": {
            "period_unit": {
                "type": "string",
                "enum": ["MONTH", "QUARTER", "YEAR", "ONE_TIME"],
            },
            "milestone_type": {
                "type": "string",
                "enum": ["DATE", "NUMERIC", "DELAY_DAYS"],
            },
            "cap_percent": {"type": "number", "minimum": 0},
        },
    }
    op.execute(
        sa.text(
            "UPDATE contract.formula_library "
            "SET parameter_schema = CAST(:schema AS jsonb) "
            "WHERE formula_type = 'fixed_escalation'"
        ).bindparams(schema=json.dumps(_original_schema))
    )

    # Revert G21
    op.drop_column("sla_definitions", "ld_computation_base", schema="contract")

    # Revert G19
    op.drop_column("sla_condition_bands", "band_group_id", schema="contract")

    # Revert G17
    op.drop_column("sla_guard_conditions", "guard_group_id", schema="contract")
