"""Carry-forward (ex-QRG) phase config + per-activity payment-term split.

Revision ID: p1a000000015
Revises: p1a000000014
Create Date: 2026-06-25

Two related Project-Finance enhancements:

1. ``project_phase_qrg`` evolves from a single ``qrg_applied`` flag into a
   per-phase CONFIG row. New columns:
     * ``sequence``               — integer phase order (the int we lost when
                                    ``phase`` became a free-text string in
                                    p1a000000014). Backfilled from the numeric
                                    phase name; drives "next/last phase".
     * ``carry_forward_enabled``  — replaces the qrg_applied semantics
                                    (backfilled from it).
     * ``carry_forward_mode``     — 'percent' | 'amount' (null when disabled).
     * ``carry_forward_percent``  — % of the phase's remaining (leftover).
     * ``carry_forward_amount``   — flat amount to carry to the next phase.
   A config row is also seeded for every distinct phase that exists on cost
   items / payment terms but has no row yet, so ordering is complete.

2. New ``project_payment_term_activities`` table — each row stores ONE
   activity's share (``percent_of_payment``) of its milestone's payment term.
   The per-activity percents sum to the milestone term's percent (enforced in
   the service). Surfaced only for partial-payment milestones.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000015"
down_revision: str = "p1a000000014"
branch_labels = None
depends_on = None


_NUMERIC = re.compile(r"^[0-9]+$")


def upgrade() -> None:
    # --- 1. project_phase_qrg -> phase config -----------------------------
    op.add_column(
        "project_phase_qrg",
        sa.Column("sequence", sa.Integer(), nullable=True),
        schema="project",
    )
    op.add_column(
        "project_phase_qrg",
        sa.Column(
            "carry_forward_enabled", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        schema="project",
    )
    op.add_column(
        "project_phase_qrg",
        sa.Column("carry_forward_mode", sa.String(length=16), nullable=True),
        schema="project",
    )
    op.add_column(
        "project_phase_qrg",
        sa.Column("carry_forward_percent", sa.Numeric(5, 2), nullable=True),
        schema="project",
    )
    op.add_column(
        "project_phase_qrg",
        sa.Column("carry_forward_amount", sa.Numeric(18, 2), nullable=True),
        schema="project",
    )

    bind = op.get_bind()
    # Backfill carry_forward_enabled from the old qrg_applied flag and the
    # sequence from a numeric phase name.
    op.execute(
        "UPDATE project.project_phase_qrg "
        "SET carry_forward_enabled = qrg_applied "
        "WHERE qrg_applied IS TRUE"
    )
    op.execute(
        "UPDATE project.project_phase_qrg "
        "SET sequence = CAST(phase AS INTEGER) "
        "WHERE phase ~ '^[0-9]+$' AND sequence IS NULL"
    )

    # Seed a config row for every distinct phase present on cost items /
    # payment terms that has no live phase-config row yet (so ordering is
    # complete for carry-forward).
    existing = {
        (pid, ph)
        for pid, ph in bind.execute(sa.text(
            "SELECT project_id, phase FROM project.project_phase_qrg "
            "WHERE deleted_at IS NULL"
        )).all()
    }
    distinct_phases = bind.execute(sa.text(
        "SELECT DISTINCT project_id, phase FROM project.project_cost_items "
        "WHERE phase IS NOT NULL AND deleted_at IS NULL "
        "UNION "
        "SELECT DISTINCT project_id, phase FROM project.project_payment_terms "
        "WHERE phase IS NOT NULL AND deleted_at IS NULL"
    )).all()
    now = datetime.now(timezone.utc)
    to_insert = []
    for pid, ph in distinct_phases:
        if (pid, ph) in existing:
            continue
        seq = int(ph) if _NUMERIC.match(str(ph) or "") else None
        to_insert.append({
            "id": str(uuid4()), "project_id": pid, "phase": ph, "sequence": seq,
            "now": now,
        })
    if to_insert:
        bind.execute(
            sa.text(
                "INSERT INTO project.project_phase_qrg "
                "(id, project_id, phase, sequence, qrg_applied, "
                " carry_forward_enabled, created_at, updated_at) "
                "VALUES (:id, :project_id, :phase, :sequence, false, false, "
                " :now, :now)"
            ),
            to_insert,
        )

    # --- 2. project_payment_term_activities -------------------------------
    op.create_table(
        "project_payment_term_activities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id", sa.String(length=36),
            sa.ForeignKey("project.projects.id"), nullable=False,
        ),
        sa.Column(
            "payment_term_id", sa.String(length=36),
            sa.ForeignKey("project.project_payment_terms.id"), nullable=False,
        ),
        sa.Column(
            "activity_id", sa.String(length=36),
            sa.ForeignKey("project.activities.id"), nullable=False,
        ),
        sa.Column("percent_of_payment", sa.Numeric(5, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "percent_of_payment IS NULL OR "
            "(percent_of_payment >= 0 AND percent_of_payment <= 100)",
            name="ck_pta_percent_range",
        ),
        schema="project",
    )
    op.create_index(
        "idx_pta_term_live", "project_payment_term_activities",
        ["payment_term_id", "deleted_at"], schema="project",
    )
    op.create_index(
        "ix_pta_activity_id", "project_payment_term_activities",
        ["activity_id"], schema="project",
    )
    op.create_index(
        "uq_pta_term_activity_live", "project_payment_term_activities",
        ["payment_term_id", "activity_id"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), schema="project",
    )


def downgrade() -> None:
    op.drop_table("project_payment_term_activities", schema="project")
    for col in (
        "carry_forward_amount", "carry_forward_percent", "carry_forward_mode",
        "carry_forward_enabled", "sequence",
    ):
        op.drop_column("project_phase_qrg", col, schema="project")
