"""
User domain model.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from ...shared.datetime import iso_ist


@dataclass
class User:
    """
    User domain entity.

    This represents the business model of a user, separate from database concerns.
    """

    # Doc 26: ``id`` is now a UUID string (was integer pre-doc-26).
    id: str
    login: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    admin: bool
    status: str
    created_at: datetime
    updated_at: datetime

    # Vendor association (single per user). Both id + name carried so the
    # API response can embed a slim vendor object without a second query.
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None

    # Division enum + free-text override when 'others'.
    division: Optional[str] = None
    division_other: Optional[str] = None

    # Phone number — required on wire create, nullable in DB so the
    # bootstrap admin row stays valid. Free-form string, max 50 chars.
    # Mirrors vendor.phone_number exactly.
    phone_number: Optional[str] = None

    # Soft-delete fields.
    deleted_at: Optional[datetime] = None
    # Doc 26: deleted_by holds a UUID string (was int pre-doc-26).
    deleted_by: Optional[str] = None

    # Doc 33 change 3: per-user 2FA flag. Default True (mandatory by
    # default at the global ``REQUIRE_2FA`` setting); admins can flip
    # to False per-user.
    two_factor_enabled: bool = True

    # Doc 25: human-readable display identifier (US-XXXX-YYMMDDHHMMSS).
    # Snapshot of ``login`` + ``created_at`` taken at create time; immutable
    # on rename. The integer ``id`` stays the canonical machine identifier
    # and FK target — ``user_code`` is purely a display / lookup convenience.
    user_code: Optional[str] = None

    # Doc 42b: separate flag for the new top-tier super_admin role.
    # Used by lockout guards (last-active super_admin protection) so
    # the admin role can be freely demoted/deactivated as long as a
    # super_admin remains. Defaults False so dataclass instantiation
    # in tests / serializers that pre-date this field stays valid.
    is_super_admin: bool = False

    # Mapped projects — populated by the repo on explicit calls (list +
    # get-by-id paths). Each entry is a slim project dict the response
    # builder embeds. Closed/completed/soft-deleted projects are
    # filtered out at the repo layer.
    projects: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """
        Convert user to dictionary.

        Returns:
            Dictionary representation of user
        """
        return {
            "id": self.id,
            "user_code": self.user_code,
            "login": self.login,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "admin": self.admin,
            "status": self.status,
            "created_at": iso_ist(self.created_at),
            "updated_at": iso_ist(self.updated_at),
            "vendor_id": self.vendor_id,
            "vendor_name": self.vendor_name,
            "division": self.division,
            "division_other": self.division_other,
            "phone_number": self.phone_number,
            "deleted_at": iso_ist(self.deleted_at),
            "deleted_by": self.deleted_by,
            "projects": list(self.projects or []),
        }

    @property
    def full_name(self) -> str:
        """
        Get full name of user.

        Returns:
            Full name or login if name not available
        """
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        return self.login

    def is_active(self) -> bool:
        """
        Check if user is active.

        Returns:
            True if user is active
        """
        return self.status == "active"

    def is_deleted(self) -> bool:
        return self.deleted_at is not None
