"""Cross-schema READ-ONLY mirror declarations for pmis-project-management.

Tables OWNED BY OTHER SERVICES that project-svc reads:

  users.* — auth + RBAC (every request via AuthMiddleware)
    - users.users
    - users.roles
    - users.user_roles                  (legacy global tier)
    - users.user_role_assignments       (Doc-41 scoped tier)
    - users.role_permissions
    - users.user_permissions
    - users.revoked_tokens

  masters.* — picker/embed data for project / milestone / activity responses
    - masters.vendors
    - masters.divisions
    - masters.priorities
    - masters.resource_types
    - masters.project_categories
    - masters.activity_statuses
    - masters.milestone_statuses
    - masters.activity_types
    - masters.project_status_transitions
    - masters.cost_types          (Project-Finance payment screen)
    - masters.frequencies         (Project-Finance payment screen)

All on `MirrorBase` — excluded from alembic autogenerate.

Canonical locations:
  users.*    → services/pmis-user-management/app/models/*
  masters.*  → services/pmis-masters-management/app/models/*

WARNING: Schema changes in canonical models MUST be replicated here.
The Q24 drift test in pmis-user-management/tests/test_cross_schema_drift.py
catches divergence (once project-svc is added to its _PEER_SERVICES list).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import MirrorBase


# =========================================================================
# users.* — read every request
# =========================================================================

class User(MirrorBase):
    __tablename__ = "users"
    __table_args__ = {"schema": "users"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_code: Mapped[Optional[str]] = mapped_column(String(24))
    login: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(255))
    # Canonical name field (mirrors users.users.full_name). The app reads
    # only full_name; first/last are gone everywhere.
    full_name: Mapped[Optional[str]] = mapped_column(String(510))
    status: Mapped[str] = mapped_column(String(16))
    vendor_id: Mapped[Optional[str]] = mapped_column(String(36))
    division: Mapped[Optional[str]] = mapped_column(String(64))
    division_other: Mapped[Optional[str]] = mapped_column(String(255))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Role(MirrorBase):
    __tablename__ = "roles"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(1024))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class UserRole(MirrorBase):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": "users"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)


class UserRoleAssignment(MirrorBase):
    __tablename__ = "user_role_assignments"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    role_id: Mapped[int] = mapped_column(Integer, index=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)


class RolePermission(MirrorBase):
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": "users"}

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(128), primary_key=True)


class UserPermission(MirrorBase):
    __tablename__ = "user_permissions"
    __table_args__ = {"schema": "users"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(128), primary_key=True)


class RevokedToken(MirrorBase):
    __tablename__ = "revoked_tokens"
    __table_args__ = {"schema": "users"}

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# =========================================================================
# masters.* — picker / embed data
# =========================================================================

class Vendor(MirrorBase):
    __tablename__ = "vendors"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vendor_code: Mapped[Optional[str]] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_person: Mapped[Optional[str]] = mapped_column(String(255))
    phone_number: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[Optional[str]] = mapped_column(String(36))


class Division(MirrorBase):
    __tablename__ = "divisions"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_other: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[str] = mapped_column(String(255))
    phone_number: Mapped[str] = mapped_column(String(50))


class Priority(MirrorBase):
    __tablename__ = "priorities"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class ResourceType(MirrorBase):
    __tablename__ = "resource_types"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectCategory(MirrorBase):
    __tablename__ = "project_categories"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_other: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(String(1024))


class ActivityType(MirrorBase):
    __tablename__ = "activity_types"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ActivityStatus(MirrorBase):
    __tablename__ = "activity_statuses"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MilestoneStatus(MirrorBase):
    __tablename__ = "milestone_statuses"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProjectStatusTransition(MirrorBase):
    """Edge in the project-status FSM. Round-7: gates by PERMISSION CODE.

    `permission_code` is the code the caller must hold to take this edge
    (scoped to the project or globally). NULL = no special permission required.
    """

    __tablename__ = "project_status_transitions"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(50))
    to_status: Mapped[str] = mapped_column(String(50))
    permission_code: Mapped[Optional[str]] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CostType(MirrorBase):
    """Project-Finance "Cost Type" dropdown source. Canonical:
    masters-svc app/models/cost_type.py. Codes: 'fixed', 'one_time'."""

    __tablename__ = "cost_types"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class PaymentType(MirrorBase):
    """Milestone "Payment Type" dropdown source. Canonical:
    masters-svc app/models/payment_type.py. Codes: 'partial_payment',
    'complete_payment'."""

    __tablename__ = "payment_types"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class CarryForwardMethod(MirrorBase):
    """Project-Finance carry-forward "method" selector source. Canonical:
    masters-svc app/models/carry_forward_method.py. Each row is a
    (method, variant) combo carrying a ``formula`` that computes the
    per-recipient carry-forward amount over a fixed variable set
    (leftover, numRecipients, recipientCycles, totalCycles, recipientPercent).
    Codes: 'milestone_evenly', 'milestone_custom', 'phase_evenly',
    'phase_custom', 'time_monthly', 'time_quarterly', 'time_half_yearly',
    'time_yearly'."""

    __tablename__ = "carry_forward_methods"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    method: Mapped[str] = mapped_column(String(16))
    variant: Mapped[str] = mapped_column(String(16))
    formula: Mapped[str] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class Frequency(MirrorBase):
    """Project-Finance "Frequency" dropdown source. Canonical:
    masters-svc app/models/frequency.py. Codes: 'one_time', 'daily',
    'monthly', 'quarterly', 'half_yearly', 'yearly'."""

    __tablename__ = "frequencies"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
