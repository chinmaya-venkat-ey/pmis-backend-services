"""
User API schemas (request/response models).
"""
from typing import List, Optional
from pydantic import (
    BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator,
)


def _split_full_name(full_name: Optional[str]):
    """Split ``"first last…"`` into ``(first, last_or_None)`` on the first
    space. Returns ``(None, None)`` for empty input. Used by both
    create and update schemas so the FE can send a single ``fullName``
    field and the BE backfills firstName / lastName from it when the
    caller didn't supply them explicitly. Mirrors the join rule used by
    the response formatter (`format_user_response`)."""
    if not full_name:
        return None, None
    parts = full_name.strip().split(" ", 1)
    first = parts[0] or None
    last = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return first, last

from ....core.permissions import (
    ADMIN_ROLE_NAME,
    DIVISION_MEMBER_ROLE_NAME,
    ORG_ADMIN_ROLE_NAME,
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_MEMBER_ROLE_NAME,
    SUPER_ADMIN_ROLE_NAME,
)
from ....domain.resource_types.resource_type import (
    DIVISION_CHOICES,
    DIVISION_OTHERS,
)


# Allowed values for the user's status field. "inactive" is what soft-deleted
# users carry; admins can also set it manually via the Edit User flow.
_USER_STATUS_CHOICES = ("active", "inactive", "locked", "registered")

# Doc 46 round 10 #3 — orgRole is now required on POST /users/create.
# Tester-feedback: "While adding a user, the Role field should be
# mandatory." The valid values are the six seeded role names.
_ORG_ROLE_CHOICES = (
    SUPER_ADMIN_ROLE_NAME,
    ADMIN_ROLE_NAME,
    ORG_ADMIN_ROLE_NAME,
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_MEMBER_ROLE_NAME,
    DIVISION_MEMBER_ROLE_NAME,
)


class ProjectAssignmentEntry(BaseModel):
    """One element of ``projectAssignments`` / ``assignments`` arrays
    (doc 44). Carries the project UUID + the role label. The role
    string is the FE-friendly display label (e.g. ``"Project Admin"``)
    rather than the canonical role name (``"project_admin"``); the
    service layer normalizes either form. Empty role string is
    accepted and means "no per-project role" — used by org_admin
    grants where the role is org-wide."""
    model_config = ConfigDict(populate_by_name=True)
    projectId: str = Field(..., alias="projectId")
    role: str = Field("", description="Role label or canonical name. Empty for org-scoped assignments.")


class UserCreateRequest(BaseModel):
    """Request schema for creating a user.

    Per product spec, every new user must have:
      - a vendor (single, FK to vendors)
      - a division (one of DIVISION_CHOICES; 'others' requires divisionOther)
      - at least one project mapping (project_ids) **unless** ``orgRole``
        is one of the global tiers (``super_admin`` / ``admin``) which
        do not need to be tied to a specific project at create time.

    Doc 44 — role-aware create:
      - ``orgRole`` (optional) sets the user's primary role at create
        time. One of: super_admin, admin, org_admin, project_admin,
        project_member. Validated against the caller's authority via
        the same caller-vs-target gate used by /role-assignments.
      - ``projectAssignments`` carries per-project role labels for
        ``project_admin`` flows (``[{projectId, role}]``). When omitted,
        each ``project_id`` gets a role assignment derived from
        ``orgRole`` directly (the org-wide role applied per project).
      - ``assignments`` is a frontend duplicate of ``projectAssignments``
        (same shape, kept for compatibility with the FE form). The
        service merges the two — anything in ``assignments`` not also
        in ``projectAssignments`` is honoured.

    The bootstrap admin path (init_db seed) bypasses this validation.
    """
    model_config = ConfigDict(populate_by_name=True)

    login: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    # Canonical name input. Split on the first space server-side into
    # first_name / last_name for DB storage; the response formatter
    # joins them back to fullName on the way out. firstName / lastName
    # are exposed as read-only @property below so existing service
    # code that reads ``data.firstName`` / ``data.lastName`` keeps
    # working unchanged.
    fullName: Optional[str] = Field(
        None, alias="full_name", max_length=510,
        description=(
            "User's full name. Split on the first space into "
            "first_name / last_name for storage — e.g. 'Saikat Aich "
            "gupta' becomes first='Saikat', last='Aich gupta'. May be "
            "omitted; in that case the DB rows are stored with NULL "
            "first/last and the response falls back to ``login`` for "
            "the fullName key."
        ),
    )
    admin: bool = False

    vendorId: str = Field(
        ..., alias="vendor_id",
        description=(
            "Vendor identifier. Accepts EITHER the vendor's UUID OR its "
            "human-readable ``vendorCode`` (e.g. ``VN-ACME-260502143015`` "
            "— see doc 25). The dispatcher auto-detects via the ``VN-`` "
            "prefix; the persisted FK is always the canonical UUID."
        ),
    )
    division: str = Field(
        ...,
        description=f"One of: {', '.join(DIVISION_CHOICES)}.",
    )
    divisionOther: Optional[str] = Field(
        None, alias="division_other", max_length=255,
        description=(
            f"Required (non-empty) when division == '{DIVISION_OTHERS}'. "
            "Must be omitted / null for any other division."
        ),
    )
    projectIds: List[str] = Field(
        default_factory=list,
        alias="project_ids",
        description=(
            "List of project UUIDs to map this user to. Optional — may "
            "be empty for any orgRole. When project-tier orgRoles "
            "(project_admin / project_member / division_member) are "
            "supplied with no project_ids, no project-scoped role rows "
            "are written; assign projects later via "
            "POST /api/v3/users/{id}/role-assignments."
        ),
    )
    phoneNumber: str = Field(
        ...,
        alias="phone_number",
        min_length=1,
        max_length=50,
        description=(
            "User's phone / mobile number. Required on create. Free-form "
            "string (no regex check — international formats vary; FE may "
            "apply its own client-side mask). Mirrors the vendor schema's "
            "``phoneNumber`` field exactly."
        ),
    )
    # Doc 46 round 10 #3 — required (was Optional in doc 44).
    # Tester-feedback: "While adding a user, the Role field should be
    # mandatory."
    orgRole: str = Field(
        ..., alias="orgRole",
        description=(
            "Primary role to grant the new user. REQUIRED. One of: "
            "super_admin, admin, org_admin, project_admin, project_member, "
            "division_member. Subject to caller-vs-target rules: "
            "super_admin can set any except super_admin (init_db only); "
            "admin can set any except super_admin / admin; org_admin can "
            "set project_admin / project_member / division_member only; "
            "project_admin can set project_member only; project_member "
            "cannot create users."
        ),
    )
    projectAssignments: Optional[List[ProjectAssignmentEntry]] = Field(
        None,
        description=(
            "Per-project role labels (doc 44). Used by the project_admin "
            "form path where each mapped project carries its own role. "
            "Each entry's projectId must also appear in project_ids."
        ),
    )
    assignments: Optional[List[ProjectAssignmentEntry]] = Field(
        None,
        description=(
            "Frontend duplicate of projectAssignments — same shape, merged "
            "with it server-side. Either field may be used; usually both "
            "are sent for project_admin and only assignments for org_admin."
        ),
    )

    @field_validator("orgRole")
    @classmethod
    def _validate_org_role(cls, v: str) -> str:
        if v not in _ORG_ROLE_CHOICES:
            raise ValueError(
                f"orgRole must be one of: {', '.join(_ORG_ROLE_CHOICES)}."
            )
        return v

    @property
    def firstName(self) -> Optional[str]:
        first, _ = _split_full_name(self.fullName)
        return first

    @property
    def lastName(self) -> Optional[str]:
        _, last = _split_full_name(self.fullName)
        return last


class UserUpdateRequest(BaseModel):
    """Request schema for updating a user."""
    model_config = ConfigDict(populate_by_name=True)

    email: Optional[EmailStr] = None
    # Canonical name input on PATCH. None / omitted leaves the existing
    # first / last unchanged; a value is split on the first space and
    # replaces BOTH fields atomically. firstName / lastName are exposed
    # as read-only @property below for the service layer.
    fullName: Optional[str] = Field(
        None, alias="full_name", max_length=510,
        description=(
            "User's full name. Omit to leave the name unchanged. "
            "When supplied, the value is split on the first space — "
            "first token becomes first_name, the remainder becomes "
            "last_name. Both columns are written; sending a single "
            "token clears last_name."
        ),
    )
    admin: Optional[bool] = None
    status: Optional[str] = None
    vendorId: Optional[str] = Field(
        None, alias="vendor_id",
        description=(
            "Vendor identifier. Accepts UUID or ``VN-...`` code (doc 25)."
        ),
    )
    division: Optional[str] = None
    divisionOther: Optional[str] = Field(
        None, alias="division_other", max_length=255,
    )
    phoneNumber: Optional[str] = Field(
        None,
        alias="phone_number",
        max_length=50,
        description=(
            "Optional on PATCH. When supplied, replaces the user's stored "
            "phone number; omit / null to leave unchanged. Mirrors the "
            "vendor PATCH schema."
        ),
    )
    # Doc 44 round 9 — round-trip parity with CREATE + GET on the
    # project-mapping field. Pre-round-9 PATCH /users/{id} only edited
    # the user's own fields (name, email, vendor, division, status);
    # changing project mappings required hitting per-user
    # role-assignments endpoints separately. Round 9 accepts
    # ``projectIds`` here so a single FE form-save can update everything.
    # ``orgRole`` and ``projectAssignments`` are deferred to a follow-up
    # — those need a richer diff/grant pipeline against the
    # caller-vs-target gate that isn't ready yet. Use POST/DELETE on
    # ``/users/{id}/role-assignments`` for now.
    projectIds: Optional[List[str]] = Field(
        None,
        alias="project_ids",
        description=(
            "Project mapping. ``None`` (omitted) leaves existing mappings "
            "unchanged; ``[]`` clears them; a non-empty list REPLACES the "
            "full project-membership set. Re-binds project-scoped role "
            "assignments accordingly: rows for projects no longer in the "
            "list are revoked; rows for new projects are granted using "
            "the user's current orgRole. Caller-vs-target rules apply "
            "per row — admin / super_admin always pass; org_admin can "
            "only operate on projects within their vendor."
        ),
    )

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v):
        if v is not None and v not in _USER_STATUS_CHOICES:
            raise ValueError(
                f"Status must be one of: {', '.join(_USER_STATUS_CHOICES)}."
            )
        return v

    @property
    def firstName(self) -> Optional[str]:
        # When fullName is omitted, return None so the update service
        # treats the name as "no change". Don't fall back to login on
        # update — that's only the response-side fallback.
        if self.fullName is None:
            return None
        first, _ = _split_full_name(self.fullName)
        return first

    @property
    def lastName(self) -> Optional[str]:
        if self.fullName is None:
            return None
        _, last = _split_full_name(self.fullName)
        return last


class UserPasswordUpdateRequest(BaseModel):
    """Request schema for updating user password."""
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    """Request schema for user login."""
    login: str
    password: str


class LoginResponse(BaseModel):
    """Response schema for user login."""
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None


class UserListQuery(BaseModel):
    """Query parameters for listing users."""
    offset: int = Field(1, ge=1, description="Page number (1-indexed)")
    pageSize: int = Field(20, ge=1, le=200, description="Number of items per page (max 200).")
    status: Optional[str] = Field(None, description="Filter by status")
    includeDeleted: bool = Field(
        False, alias="include_deleted",
        description="Admin-only: also surface soft-deleted users.",
    )


class IntrospectRequest(BaseModel):
    """Request schema for token introspection.

    RFC 7662-style: pure read-only metadata lookup, never rotates tokens.
    Provide either or both fields. Both → response shape becomes
    ``{access: {...}, refresh: {...}}``.
    """

    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class RefreshRequest(BaseModel):
    """Request schema for POST /users/refresh.

    Takes only a refresh token. Successful rotation returns a new
    access + refresh pair plus expiry metadata so the FE can schedule
    the next preemptive refresh without decoding the JWT.
    """

    refresh_token: str


# ---------------------------------------------------------------------------
# Doc 33 change 3 — 2FA + forgot-password schemas
# ---------------------------------------------------------------------------

class OtpSendRequest(BaseModel):
    """POST /users/login/send-otp body."""

    ephemeral_token: str = Field(..., min_length=10)
    channel: str = Field(..., description="email or sms")


class OtpVerifyRequest(BaseModel):
    """POST /users/login/verify-otp body."""

    ephemeral_token: str = Field(..., min_length=10)
    code: str = Field(..., min_length=4, max_length=12)


class ForgotPasswordRequest(BaseModel):
    """POST /users/forgot-password body. Anti-enumeration: this endpoint
    always returns 200, whether the user exists or not."""

    login_or_email: str = Field(..., min_length=1, max_length=255)
    channel: str = Field(..., description="email or sms")


class ResetPasswordRequest(BaseModel):
    """POST /users/reset-password body. Accepts either a URL-safe token
    (email channel) or a numeric OTP (sms channel) — the server hashes
    and matches whichever form was sent."""

    token_or_code: str = Field(..., min_length=4, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=255)
