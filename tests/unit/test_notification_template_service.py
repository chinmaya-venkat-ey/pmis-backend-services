"""Unit tests for the NotificationTemplate restore conflict guard.

Verifies the Option (a) decision: restore is rejected if another row is
already active for the same (template_kind, channel).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.errors import CatalogEntryConflictError


def _make_template(*, template_id, kind, channel, active, is_builtin=False):
    row = MagicMock(name=f"NotificationTemplate({template_id})")
    row.id = template_id
    row.template_kind = kind
    row.channel = channel
    row.subject = "..."
    row.body = "..."
    row.is_html = True
    row.is_builtin = is_builtin
    row.active = active
    row.description = None
    return row


def test_restore_rejects_when_another_active_template_for_pair():
    """Day-10 scenario from the user-facing explanation:
       T1 (deactivated) + T2 (active) for (otp_login, email).
       Restoring T1 must fail with a clear conflict.
    """
    from app.services.notification_template_service import NotificationTemplateService

    db = MagicMock()
    svc = NotificationTemplateService(db)

    inactive_T1 = _make_template(template_id=17, kind="otp_login", channel="email", active=False)
    active_T2 = _make_template(template_id=28, kind="otp_login", channel="email", active=True)

    svc.repo.get_by_id = MagicMock(return_value=inactive_T1)
    svc.repo.find_active = MagicMock(return_value=active_T2)

    with pytest.raises(CatalogEntryConflictError) as exc_info:
        svc.restore(17)
    assert exc_info.value.code == "CATALOG_ENTRY_CONFLICT"
    assert exc_info.value.details["conflicting_id"] == 28


def test_restore_succeeds_when_no_other_active():
    """If no other row is active, the restore proceeds cleanly."""
    from app.services.notification_template_service import NotificationTemplateService

    db = MagicMock()
    svc = NotificationTemplateService(db)

    inactive_T1 = _make_template(template_id=17, kind="otp_login", channel="email", active=False)
    svc.repo.get_by_id = MagicMock(return_value=inactive_T1)
    svc.repo.find_active = MagicMock(return_value=None)
    svc.repo.reactivate = MagicMock(return_value=inactive_T1)

    svc.restore(17)
    svc.repo.reactivate.assert_called_once_with(inactive_T1)


def test_create_rejects_when_active_row_exists_for_pair():
    """Existing CREATE guard — separate from the restore guard."""
    from app.services.notification_template_service import NotificationTemplateService
    from app.schemas.notification_template import NotificationTemplateCreateRequest

    db = MagicMock()
    svc = NotificationTemplateService(db)
    existing = _make_template(template_id=17, kind="otp_login", channel="email", active=True)
    svc.repo.find_by_kind_and_channel_any = MagicMock(return_value=existing)

    payload = NotificationTemplateCreateRequest(
        template_kind="otp_login",
        channel="email",
        subject="Your code: {code}",
        body="Hi! Code: {code}",
    )
    with pytest.raises(CatalogEntryConflictError):
        svc.create(payload)


def test_delete_does_not_block_builtin():
    """Per user direction: is_builtin is informational only."""
    from app.services.notification_template_service import NotificationTemplateService

    db = MagicMock()
    svc = NotificationTemplateService(db)
    builtin = _make_template(template_id=1, kind="otp_login", channel="email", active=True, is_builtin=True)
    svc.repo.get_by_id = MagicMock(return_value=builtin)
    svc.repo.deactivate = MagicMock(return_value=builtin)

    svc.delete(1)
    svc.repo.deactivate.assert_called_once_with(builtin)
