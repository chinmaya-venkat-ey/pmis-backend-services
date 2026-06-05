"""Seed built-in rows for the masters catalogs.

Idempotent (`ON CONFLICT DO NOTHING` on unique-constraint clashes) so the
migration runs cleanly whether the tables are empty (fresh env — seeds rows)
or already populated from cutover data copy (no-op).

Seeded:
  - priorities: P1 (high), P2 (medium), P3 (low)
  - milestone_statuses: not_started, in_progress, completed, blocked, cancelled
  - activity_statuses:  not_started, in_progress, completed, blocked, cancelled
  - project_status_transitions: the project lifecycle edge graph
  - notification_templates: otp_login + password_reset built-ins (email + sms)

NOT seeded here (operator/env-dependent or organic):
  - divisions: depends on DIVISION_DEFAULT_EMAIL / DIVISION_DEFAULT_PHONE env vars; seeded
    by a separate operator-run script or the bootstrap data-migration when those values
    are available.
  - vendors, resource_types, project_categories, activity_types: no built-ins (organic
    catalog growth from day 1).

Revision ID: m1a000000002
Revises: m1a000000001
Create Date: 2026-05-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "m1a000000002"
down_revision = "m1a000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- priorities ----------------------------------------------------
    # Position semantics: lower = higher priority. P1 = position 1 (highest).
    op.execute(
        sa.text("""
        INSERT INTO masters.priorities (id, code, name, description, position, active, is_builtin)
        VALUES
            (gen_random_uuid()::text, 'P1', 'High',   'Highest priority — addresses first',  1, true, true),
            (gen_random_uuid()::text, 'P2', 'Medium', 'Default priority for most work',      2, true, true),
            (gen_random_uuid()::text, 'P3', 'Low',    'Lowest priority — addresses last',    3, true, true)
        ON CONFLICT (code) DO NOTHING
        """)
    )

    # --- milestone_statuses --------------------------------------------
    op.execute(
        sa.text("""
        INSERT INTO masters.milestone_statuses (code, label, is_builtin, is_terminal, active)
        VALUES
            ('not_started', 'Not started',  true, false, true),
            ('in_progress', 'In progress',  true, false, true),
            ('completed',   'Completed',    true, true,  true),
            ('blocked',     'Blocked',      true, false, true),
            ('cancelled',   'Cancelled',    true, true,  true)
        ON CONFLICT (code) DO NOTHING
        """)
    )

    # --- activity_statuses ---------------------------------------------
    op.execute(
        sa.text("""
        INSERT INTO masters.activity_statuses (code, label, is_builtin, is_terminal, active)
        VALUES
            ('not_started', 'Not started',  true, false, true),
            ('in_progress', 'In progress',  true, false, true),
            ('completed',   'Completed',    true, true,  true),
            ('blocked',     'Blocked',      true, false, true),
            ('cancelled',   'Cancelled',    true, true,  true)
        ON CONFLICT (code) DO NOTHING
        """)
    )

    # --- project_status_transitions ------------------------------------
    # Round-7: each edge carries a permission_code. The caller must hold
    # that code scoped to the project (or globally) to take the transition.
    # NULL permission_code = no special permission needed (initial seed +
    # universal edges).
    op.execute(
        sa.text("""
        INSERT INTO masters.project_status_transitions
            (from_status, to_status, permission_code, active, description)
        VALUES
            (NULL,         'new',         NULL,                 true, 'Initial status accepted on a fresh create'),
            -- §3.12 (2026-06-02 audit): permission_code dropped from this
            -- edge after `projects:draft` was deleted from the canonical
            -- catalog; the column is stored but not consulted for authz.
            ('new',        'draft',       NULL,                 true, 'First save — wizard step 1 complete'),
            ('draft',      'published',   'projects:publish',   true, 'Project goes live'),
            ('draft',      'cancelled',   'projects:close',     true, 'Abandon a draft before publishing'),
            ('published',  'in_progress', 'projects:publish',   true, 'Active work has begun'),
            ('in_progress','review',      'projects:publish',   true, 'Awaiting closure approval'),
            ('review',     'in_progress', 'projects:reopen',    true, 'Reopen for more work'),
            ('review',     'closed',      'projects:close',     true, 'Final close — needs projects:close'),
            ('published',  'closed',      'projects:close',     true, 'Direct close from published'),
            ('in_progress','cancelled',   'projects:close',     true, 'Mid-flight cancel')
        ON CONFLICT ON CONSTRAINT uq_project_status_transitions_edge DO NOTHING
        """)
    )

    # --- notification_templates ----------------------------------------
    op.execute(
        sa.text("""
        INSERT INTO masters.notification_templates
            (template_kind, channel, subject, body, is_html, is_builtin, active, description)
        VALUES
            (
                'otp_login', 'email',
                'Your PMIS one-time code',
                '<p>Hello,</p><p>Your PMIS one-time code is <b>{code}</b>. It expires in {ttl_minutes} minutes.</p><p>If you did not request this code you can safely ignore this email.</p>',
                true, true, true,
                'Built-in: login OTP delivered by email'
            ),
            (
                'otp_login', 'sms',
                NULL,
                'PMIS code: {code} (valid {ttl_minutes} min)',
                false, true, true,
                'Built-in: login OTP delivered by SMS'
            ),
            (
                'password_reset_link', 'email',
                'Reset your PMIS password',
                '<p>Hello,</p><p>To reset your PMIS password, click the link below within {ttl_minutes} minutes:</p><p><a href="{reset_url}">{reset_url}</a></p><p>If you did not request this, you can safely ignore this email.</p>',
                true, true, true,
                'Built-in: password-reset link email'
            ),
            (
                'password_reset_otp', 'sms',
                NULL,
                'PMIS password reset code: {code} (valid {ttl_minutes} min)',
                false, true, true,
                'Built-in: password-reset OTP via SMS'
            ),
            (
                'project_deadline_digest', 'email',
                'PMIS — projects with upcoming deadlines',
                '<p>Hello {full_name},</p><p>The following PMIS items have deadlines this week:</p>{items_html}<p><a href="{portal_url}">Open PMIS</a></p>',
                true, true, true,
                'Built-in: daily deadline-digest email (sent by notification-svc cron)'
            )
        ON CONFLICT DO NOTHING
        """)
    )


def downgrade() -> None:
    """Remove the builtin rows. Note: down does NOT remove user-created rows."""
    op.execute(sa.text("DELETE FROM masters.notification_templates WHERE is_builtin = true"))
    op.execute(sa.text("DELETE FROM masters.project_status_transitions"))
    op.execute(sa.text("DELETE FROM masters.activity_statuses WHERE is_builtin = true"))
    op.execute(sa.text("DELETE FROM masters.milestone_statuses WHERE is_builtin = true"))
    op.execute(sa.text("DELETE FROM masters.priorities WHERE is_builtin = true"))
