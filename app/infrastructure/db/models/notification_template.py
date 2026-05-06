"""Notification template catalog (doc 36).

Replaces the hardcoded if/elif/else blocks in
``app/shared/notifications.py``: ``_render_email`` and ``_render_sms``
now look up active rows here by ``(template_kind, channel)`` and run
``str.format(**placeholders)`` over the stored ``subject`` / ``body``.

Three template kinds ship as built-in seed rows on first boot
(``otp_login``, ``password_reset_link``, ``password_reset_otp``), each
with both an ``email`` and an ``sms`` flavor where applicable. Built-in
rows are protected from delete but their copy IS editable via the
master-data API — that's the point of moving templates to DB. Ops can
edit subject + body without a release.

Lookup contract:
- Renderer pulls the latest ``active=True`` row matching
  ``(template_kind, channel)``.
- Service layer guarantees at most one active row per
  ``(kind, channel)`` pair (uniqueness check on PATCH/POST).
- When no active row matches, the renderer falls back to a generic
  "you have a notification" body and logs a warning. Notifications must
  not crash the auth flow even when the catalog has been mis-edited.

Placeholder spec (validated at write time on PATCH/POST so a bad
reference is rejected up front, not at dispatch time):

  otp_login (email + sms):       {code} {ttl_minutes}
  password_reset_link (email):   {reset_url} {token} {ttl_minutes}
  password_reset_link (sms):     {token} {ttl_minutes}
  password_reset_otp (email + sms): {code} {ttl_minutes}

Computed placeholders (e.g. ``ttl_minutes`` from ``ttl_seconds``,
``reset_url`` from ``FRONTEND_BASE_URL`` + ``token``) are derived in
the renderer before substitution — the stored template only sees the
already-computed values.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Index, Integer, String, Text, UniqueConstraint

from ..session import Base
from ..utc_datetime import UtcDateTime


def _utcnow():
    return datetime.now(timezone.utc)


class NotificationTemplateModel(Base):
    __tablename__ = "notification_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ``otp_login`` / ``password_reset_link`` / ``password_reset_otp`` /
    # future kinds. Free-form so admins can register new kinds at runtime
    # to match new dispatch sites added in code.
    template_kind = Column(String(64), nullable=False, index=True)

    # ``email`` or ``sms``.
    channel = Column(String(16), nullable=False, index=True)

    # Email subject. NULL for SMS rows (SMS has no subject concept).
    subject = Column(String(500), nullable=True)

    # Email HTML body or SMS plaintext. ``str.format(**placeholders)``
    # at render time. Required for both channels.
    body = Column(Text, nullable=False)

    # TRUE for email rows (HTML body); FALSE for SMS. Forwarded to the
    # notification microservice's ``is_html`` field on POST .../email/send.
    is_html = Column(Boolean, default=True, nullable=False)

    # TRUE for the seeded templates; protected from hard delete. Subject
    # and body ARE editable on built-ins (the whole point of moving
    # templates to DB).
    is_builtin = Column(Boolean, default=False, nullable=False)

    # Soft-deactivate without delete. Renderer falls back to a generic
    # body when no active row matches.
    active = Column(Boolean, default=True, nullable=False, index=True)

    # Free-form ops note (e.g. "Sent on every successful 2FA login attempt").
    description = Column(String(1024), nullable=True)

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(
        UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False,
    )

    __table_args__ = (
        # At most one ACTIVE row per (kind, channel). Soft-deactivated
        # rows can coexist (history-safe). Enforced by the route layer
        # too — this is the belt-and-braces DB guard.
        #
        # NOTE: SQLite supports partial-unique indexes only via raw DDL,
        # not via UniqueConstraint(). The full enforcement lives in the
        # alembic migration with ``CREATE UNIQUE INDEX ... WHERE active``;
        # here we declare a non-unique composite index so the lookup
        # query stays fast on SQLite where the partial index is absent.
        Index(
            "idx_notification_templates_kind_channel_active",
            "template_kind", "channel", "active",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationTemplateModel(id={self.id}, "
            f"kind='{self.template_kind}', channel='{self.channel}', "
            f"active={self.active}, builtin={self.is_builtin})>"
        )
