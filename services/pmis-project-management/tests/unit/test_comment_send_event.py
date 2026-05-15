"""Unit tests for the Doc-35 "send-event" comment model.

Both the schema validator AND the CommentService enforce:
  - body OR attachments must be present (else reject)
  - attachment size cap (settings.attachments_max_bytes)
  - attachment extension allow-list (settings.attachments_allowed_extensions)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.core.errors import (
    AttachmentDisallowedExtensionError,
    AttachmentTooLargeError,
    CommentBodyOrAttachmentRequiredError,
)
from app.schemas.comment import CommentAttachment, CommentCreateRequest


# --- Schema validator -----------------------------------------------------

def test_schema_rejects_empty_body_and_attachments():
    with pytest.raises(ValidationError) as exc:
        CommentCreateRequest(body=None, attachments=None)
    assert "body or attachments must be present" in str(exc.value)


def test_schema_rejects_blank_body_no_attachments():
    with pytest.raises(ValidationError):
        CommentCreateRequest(body="   ", attachments=None)


def test_schema_accepts_body_only():
    req = CommentCreateRequest(body="hello", attachments=None)
    assert req.body == "hello"


def test_schema_accepts_attachments_only():
    req = CommentCreateRequest(
        body=None,
        attachments=[CommentAttachment(url="https://x/y.pdf", filename="y.pdf")],
    )
    assert len(req.attachments) == 1


# --- Service-layer attachment guards --------------------------------------

def test_service_rejects_too_large_attachment(monkeypatch):
    from app.services import comment_service as cs

    monkeypatch.setattr(cs.settings, "attachments_max_bytes", 100, raising=False)
    svc = cs.CommentService(MagicMock())

    payload = CommentCreateRequest(
        body=None,
        attachments=[CommentAttachment(
            url="https://x/y.pdf", filename="y.pdf", sizeBytes=200,
        )],
    )
    with pytest.raises(AttachmentTooLargeError):
        svc.create(
            project_id="p-1", target_kind="milestone", target_id="m-1",
            payload=payload, caller_user_id="u-1",
        )


def test_service_rejects_disallowed_extension(monkeypatch):
    from app.services import comment_service as cs

    monkeypatch.setattr(cs.settings, "attachments_allowed_extensions", "pdf,docx", raising=False)
    monkeypatch.setattr(cs.settings, "attachments_max_bytes", 10_000_000, raising=False)
    svc = cs.CommentService(MagicMock())

    payload = CommentCreateRequest(
        body=None,
        attachments=[CommentAttachment(url="https://x/y.exe", filename="y.exe", sizeBytes=10)],
    )
    with pytest.raises(AttachmentDisallowedExtensionError):
        svc.create(
            project_id="p-1", target_kind="milestone", target_id="m-1",
            payload=payload, caller_user_id="u-1",
        )


def test_service_rejects_empty_body_and_attachments(monkeypatch):
    """Even with the schema validator stripped, the service-side guard fires."""
    from app.services import comment_service as cs

    svc = cs.CommentService(MagicMock())
    payload = CommentCreateRequest.model_construct(body=None, attachments=None)

    with pytest.raises(CommentBodyOrAttachmentRequiredError):
        svc.create(
            project_id="p-1", target_kind="milestone", target_id="m-1",
            payload=payload, caller_user_id="u-1",
        )
