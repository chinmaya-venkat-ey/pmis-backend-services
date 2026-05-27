"""Refactor: replace contracts/contract_phases/contract_scoring_config with project_ld_config.

A "contract" is the same entity as a "project" in the project module.
This migration removes the redundant contract entity and replaces it with
a lightweight `project_ld_config` table that holds only the LD-specific
financial terms (contract_ref, total_value, quarterly_ld_cap_percent,
scoring config) keyed by project_id (soft FK to project.projects.id).

Changes:
  - CREATE  contract.project_ld_config
  - ALTER   contract.sla_definitions:
              DROP contract_id (FK to contracts), DROP phase_id (FK to contract_phases)
              ADD  FK on existing project_id column → project_ld_config.project_id
              DROP old indexes, ADD ix_sla_def_project_sla_ref (unique)
  - ALTER   contract.evaluation_results:
              DROP contract_id (FK to contracts)
              ADD  project_id (FK to project_ld_config.project_id)
  - DROP    contract.contract_scoring_config
  - DROP    contract.contract_phases
  - DROP    contract.contracts

Revision ID: 0004_project_ld_refactor
Revises: 0003_g25_g26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_project_ld_refactor"
down_revision = "0003_g25_g26"
branch_labels = None
depends_on = None

VALID_LD_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED", "EXPIRED", "TERMINATED")


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Create project_ld_config
    #    project_id is the soft FK to project.projects.id (cross-service, no DB FK).
    #    It is UNIQUE — one LD config per project.
    # -----------------------------------------------------------------------
    op.create_table(
        "project_ld_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("contract_ref", sa.String(100), nullable=False),
        sa.Column("total_value", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(10), nullable=False, server_default="INR"),
        sa.Column("quarterly_ld_cap_percent", sa.Numeric(5, 2)),
        sa.Column(
            "ld_status", sa.String(20), nullable=False, server_default="ACTIVE"
        ),
        # MSAP/PMU scoring config — NULL for BSP/MSIP
        sa.Column("severity_points_map", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("points_ld_map", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "scoring_applies_to",
            postgresql.ARRAY(sa.String(64)),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_by", sa.String(36)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        schema="contract",
    )
    op.create_index(
        "ix_plc_project_id", "project_ld_config", ["project_id"],
        unique=True, schema="contract",
    )
    op.create_index(
        "ix_plc_contract_ref", "project_ld_config", ["contract_ref"],
        unique=True, schema="contract",
    )
    op.create_index(
        "ix_plc_ld_status", "project_ld_config", ["ld_status"], schema="contract",
    )

    # -----------------------------------------------------------------------
    # 2. Rewire sla_definitions
    #    - Drop FK + column: contract_id
    #    - Drop FK + column: phase_id  (milestone_id already exists from G25)
    #    - Add FK on existing project_id → project_ld_config.project_id
    #    - Drop old contract-scoped indexes, add project-scoped ones
    # -----------------------------------------------------------------------
    # Drop old indexes first
    op.drop_index("ix_sla_def_contract_id", table_name="sla_definitions", schema="contract")
    op.drop_index("ix_sla_def_contract_sla_ref", table_name="sla_definitions", schema="contract")
    op.drop_index("ix_sla_def_phase_id", table_name="sla_definitions", schema="contract")

    # Drop FK constraints (PostgreSQL names them automatically)
    op.drop_constraint(
        "sla_definitions_contract_id_fkey", "sla_definitions",
        schema="contract", type_="foreignkey",
    )
    op.drop_constraint(
        "sla_definitions_phase_id_fkey", "sla_definitions",
        schema="contract", type_="foreignkey",
    )

    # Drop the columns
    op.drop_column("sla_definitions", "contract_id", schema="contract")
    op.drop_column("sla_definitions", "phase_id", schema="contract")

    # Add FK on project_id → project_ld_config.project_id
    op.create_foreign_key(
        "fk_sla_def_project_id",
        "sla_definitions", "project_ld_config",
        ["project_id"], ["project_id"],
        source_schema="contract", referent_schema="contract",
        ondelete="CASCADE",
    )

    # ix_sla_def_project_id already exists from migration 0003 — don't recreate it.
    # Add the new unique composite index: (project_id, sla_ref)
    op.create_index(
        "ix_sla_def_project_sla_ref", "sla_definitions", ["project_id", "sla_ref"],
        unique=True, schema="contract",
    )

    # -----------------------------------------------------------------------
    # 3. Rewire evaluation_results
    #    - Drop FK + column: contract_id
    #    - Add project_id (FK → project_ld_config.project_id)
    # -----------------------------------------------------------------------
    op.drop_index("ix_eval_results_contract_id", table_name="evaluation_results", schema="contract")
    op.drop_constraint(
        "evaluation_results_contract_id_fkey", "evaluation_results",
        schema="contract", type_="foreignkey",
    )
    op.drop_column("evaluation_results", "contract_id", schema="contract")

    op.add_column(
        "evaluation_results",
        sa.Column("project_id", sa.String(36), nullable=False, server_default=""),
        schema="contract",
    )
    op.create_foreign_key(
        "fk_eval_results_project_id",
        "evaluation_results", "project_ld_config",
        ["project_id"], ["project_id"],
        source_schema="contract", referent_schema="contract",
    )
    op.create_index(
        "ix_eval_results_project_id", "evaluation_results", ["project_id"], schema="contract",
    )

    # -----------------------------------------------------------------------
    # 4. Drop the now-unused tables (FK-dependency order)
    # -----------------------------------------------------------------------
    op.drop_table("contract_scoring_config", schema="contract")
    op.drop_table("contract_phases", schema="contract")
    op.drop_table("contracts", schema="contract")


def downgrade() -> None:
    # Restore contracts
    op.create_table(
        "contracts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contract_ref", sa.String(100), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("vendor_name", sa.String(255), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("total_value", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(10), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("quarterly_ld_cap_percent", sa.Numeric(5, 2)),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(36)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_table(
        "contract_phases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contract_id", sa.String(36), sa.ForeignKey("contract.contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phase_name", sa.String(255), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_table(
        "contract_scoring_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contract_id", sa.String(36), sa.ForeignKey("contract.contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("severity_points_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("points_ld_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("applies_to_formulas", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )

    # Restore evaluation_results.contract_id
    op.drop_index("ix_eval_results_project_id", table_name="evaluation_results", schema="contract")
    op.drop_constraint("fk_eval_results_project_id", "evaluation_results", schema="contract", type_="foreignkey")
    op.drop_column("evaluation_results", "project_id", schema="contract")
    op.add_column("evaluation_results", sa.Column("contract_id", sa.String(36), sa.ForeignKey("contract.contracts.id"), nullable=False, server_default=""), schema="contract")
    op.create_index("ix_eval_results_contract_id", "evaluation_results", ["contract_id"], schema="contract")

    # Restore sla_definitions columns
    op.drop_constraint("fk_sla_def_project_id", "sla_definitions", schema="contract", type_="foreignkey")
    op.drop_index("ix_sla_def_project_sla_ref", table_name="sla_definitions", schema="contract")
    # ix_sla_def_project_id is owned by migration 0003 — leave it for 0003's downgrade.
    op.add_column("sla_definitions", sa.Column("contract_id", sa.String(36), sa.ForeignKey("contract.contracts.id", ondelete="CASCADE"), nullable=False, server_default=""), schema="contract")
    op.add_column("sla_definitions", sa.Column("phase_id", sa.String(36), sa.ForeignKey("contract.contract_phases.id", ondelete="SET NULL")), schema="contract")
    op.create_index("ix_sla_def_contract_id", "sla_definitions", ["contract_id"], schema="contract")
    op.create_index("ix_sla_def_contract_sla_ref", "sla_definitions", ["contract_id", "sla_ref"], unique=True, schema="contract")
    op.create_index("ix_sla_def_phase_id", "sla_definitions", ["phase_id"], schema="contract")

    # Drop project_ld_config
    op.drop_table("project_ld_config", schema="contract")
