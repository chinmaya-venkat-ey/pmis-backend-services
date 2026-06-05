"""Unit tests for TemplateService — render fallback + placeholder computation."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_render_email_fallback_when_no_active_template():
    """Missing template → fallback subject + body, doesn't raise."""
    from app.repositories.notification_template_repository import (
        NotificationTemplateRepository,
    )
    from app.services.template_service import TemplateService, _FALLBACK_EMAIL_SUBJECT

    db = MagicMock()
    original = NotificationTemplateRepository.find_active
    NotificationTemplateRepository.find_active = lambda self, **kwargs: None

    try:
        svc = TemplateService(db)
        subject, body, is_html = svc.render_email("nonexistent_kind", {})
        assert subject == _FALLBACK_EMAIL_SUBJECT
        assert "PMIS" in body
        assert is_html is True
    finally:
        NotificationTemplateRepository.find_active = original


def test_render_email_computes_ttl_minutes_for_otp_login():
    """ttl_seconds → ttl_minutes substitution."""
    from app.repositories.notification_template_repository import (
        NotificationTemplateRepository,
    )
    from app.services.template_service import TemplateService

    fake_template = MagicMock()
    fake_template.subject = "Code: {code}"
    fake_template.body = "Use {code} within {ttl_minutes} minutes."
    fake_template.is_html = False

    original = NotificationTemplateRepository.find_active
    NotificationTemplateRepository.find_active = lambda self, **kwargs: fake_template

    try:
        svc = TemplateService(MagicMock())
        subject, body, _ = svc.render_email(
            "otp_login", {"code": "555000", "ttl_seconds": 600}
        )
        assert "555000" in subject
        assert "555000" in body
        assert "10" in body  # 600/60 = 10 minutes
    finally:
        NotificationTemplateRepository.find_active = original


def test_render_sms_fallback_when_no_active_template():
    from app.repositories.notification_template_repository import (
        NotificationTemplateRepository,
    )
    from app.services.template_service import TemplateService, _FALLBACK_SMS_BODY

    original = NotificationTemplateRepository.find_active
    NotificationTemplateRepository.find_active = lambda self, **kwargs: None

    try:
        svc = TemplateService(MagicMock())
        body = svc.render_sms("nonexistent_kind", {})
        assert body == _FALLBACK_SMS_BODY
    finally:
        NotificationTemplateRepository.find_active = original


def test_render_email_missing_placeholder_falls_back_to_empty_string():
    """str.format_map with _SafeDict substitutes "" for missing keys (no KeyError)."""
    from app.repositories.notification_template_repository import (
        NotificationTemplateRepository,
    )
    from app.services.template_service import TemplateService

    fake_template = MagicMock()
    fake_template.subject = "Hi {full_name}"
    fake_template.body = "Subject only: {nonexistent_placeholder}"
    fake_template.is_html = False

    original = NotificationTemplateRepository.find_active
    NotificationTemplateRepository.find_active = lambda self, **kwargs: fake_template

    try:
        svc = TemplateService(MagicMock())
        subject, body, _ = svc.render_email("anything", {"full_name": "Alice"})
        assert subject == "Hi Alice"
        # The {nonexistent_placeholder} renders as empty string, not raising
        assert "nonexistent_placeholder" not in body
    finally:
        NotificationTemplateRepository.find_active = original
