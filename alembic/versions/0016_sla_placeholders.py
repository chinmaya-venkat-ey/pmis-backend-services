"""Add ``placeholders`` JSONB column to sla_definitions.

A placeholder declares what the *operator* has to fill in when the SLA
template is attached to an activity. Each item looks like::

    {
      "key":          "deliverable_cost",      # machine name; goes into mapping.overrides
      "label":        "Cost of this deliverable",
      "type":         "money",                 # money | date | number | text
      "required":     true,
      "default_from": null,                    # or "activity.start_date", etc.
      "help":         "Used as the LD% base. RFP §5.28.2.b."
    }

The mapping form renders one input per placeholder declared on the chosen
SLA — no static T-anchor / actual-start / actual-end / LD-base fields
anymore, just whatever the template needs. SLAs with no per-mapping
variables (PMU-SLA005, 006, 007, 011 etc.) carry an empty array and the
form has nothing to ask the operator.

The column is nullable + defaults to ``'[]'::jsonb`` so existing rows
remain valid.

Revision ID: 0016_sla_placeholders
Revises: 0015_sla_category_master
Create Date: 2026-06-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0016_sla_placeholders"
down_revision = "0015_sla_category_master"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sla_definitions",
        sa.Column(
            "placeholders",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema="contract",
    )


def downgrade() -> None:
    op.drop_column("sla_definitions", "placeholders", schema="contract")
