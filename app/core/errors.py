"""Domain error hierarchy — CANONICAL declaration site.

Services raise these; the @app.exception_handler in middleware/error_handler.py
translates them to consistent JSON envelopes. No HTTPException in service code.

WARNING: This file is the canonical version. Other services duplicate it:
  - services/pmis-masters-management/app/core/errors.py
  - services/pmis-notification-management/app/core/errors.py
  - services/pmis-project-management/app/core/errors.py
Keep in sync by hand until tools/check_canonical_drift.py is wired.
"""
from __future__ import annotations

from typing import Optional


class DomainError(Exception):
    """Base for all expected errors."""

    status_code: int = 500
    default_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "",
        *,
        code: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.details = details or {}


class NotFoundError(DomainError):
    status_code = 404
    default_code = "NOT_FOUND"


class ConflictError(DomainError):
    status_code = 409
    default_code = "CONFLICT"


class ForbiddenError(DomainError):
    status_code = 403
    default_code = "FORBIDDEN"


class UnauthorizedError(DomainError):
    status_code = 401
    default_code = "UNAUTHORIZED"


class ValidationError(DomainError):
    status_code = 422
    default_code = "VALIDATION_ERROR"


# user-svc-specific subclasses
class UserNotFoundError(NotFoundError):
    default_code = "USER_NOT_FOUND"


class UserLoginAlreadyInUseError(ConflictError):
    default_code = "USER_LOGIN_IN_USE"


class UserEmailAlreadyInUseError(ConflictError):
    default_code = "USER_EMAIL_IN_USE"


class InvalidCredentialsError(UnauthorizedError):
    default_code = "INVALID_CREDENTIALS"


class TwoFactorRequiredError(UnauthorizedError):
    """Not an error per se — signals to the controller that 2FA is needed."""

    default_code = "TWO_FACTOR_REQUIRED"
    status_code = 200  # caller responds with a special body, not an error

    def __init__(self, message: str = "", *, ephemeral_token: str, channels_available: list[str], **kw):
        super().__init__(message, **kw)
        self.details = {
            **(kw.get("details") or {}),
            "ephemeral_token": ephemeral_token,
            "channels_available": channels_available,
        }


class OtpInvalidError(UnauthorizedError):
    default_code = "OTP_INVALID"


class OtpExpiredError(UnauthorizedError):
    default_code = "OTP_EXPIRED"


class OtpAttemptsExceededError(UnauthorizedError):
    default_code = "OTP_ATTEMPTS_EXCEEDED"


class RefreshTokenInvalidError(UnauthorizedError):
    default_code = "REFRESH_TOKEN_INVALID"


class PasswordResetTokenInvalidError(UnauthorizedError):
    default_code = "PASSWORD_RESET_TOKEN_INVALID"


class LastSuperAdminLockoutError(ConflictError):
    """Can't delete / demote the only remaining super_admin."""

    default_code = "LAST_SUPER_ADMIN_LOCKOUT"


class CallerCannotModifyTargetError(ForbiddenError):
    """Doc-44 caller-vs-target gate. e.g. org_admin trying to edit admin."""

    default_code = "CALLER_CANNOT_MODIFY_TARGET"


class CallerCannotGrantRoleError(ForbiddenError):
    """Caller's role doesn't authorize granting this role to that scope."""

    default_code = "CALLER_CANNOT_GRANT_ROLE"
