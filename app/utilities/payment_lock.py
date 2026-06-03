"""Publish-lock for the payment module.

Per requirement: payment data is editable through onboarding (new / draft)
and LOCKED once the project is published or beyond — EXCEPT for super_admin
/ pmis admin, who may edit after publish (admin bypass via
``request.state.is_admin``).

This mirrors the v1 finance publish-lock intent but adds the admin bypass.
"""
from __future__ import annotations

from app.core.errors import ConflictError


# Statuses at/after publish — payment fields are frozen for non-admins.
_LOCKED_STATUSES = frozenset({"published", "in_progress", "review", "closed"})


def is_payment_locked(status: object) -> bool:
    return (str(status or "").lower()) in _LOCKED_STATUSES


def assert_payment_writable(project, *, caller_is_admin: bool) -> None:
    """Raise 409 when the project is published-or-beyond and the caller is
    not an admin. Admins (super_admin / pmis admin) always pass."""
    if caller_is_admin:
        return
    if is_payment_locked(getattr(project, "status", None)):
        raise ConflictError(
            "Payment / finance fields are locked once the project is published. "
            "Only an administrator can edit them after publish.",
            code="conflict",
            details={
                "project_id": getattr(project, "id", None),
                "project_status": getattr(project, "status", None),
            },
        )
