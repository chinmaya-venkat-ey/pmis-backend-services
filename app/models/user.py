"""User SQLAlchemy model — owned by pmis-user-management (schema `users`).

UUID primary key (Doc-26 flipped from int). Soft-delete via deleted_at +
deleted_by (FK to users.id, self-reference). Refresh-token rotation columns
(refresh_token_jti + previous_refresh_token_jti + valid-until) per Doc-33+.

WARNING: This model is MIRRORED in read-only declarations in:
  - services/pmis-project-management/app/models/_cross_schema.py
  - services/pmis-notification-management/app/models/_cross_schema.py
  - services/pmis-masters-management/app/models/_cross_schema.py
Schema changes here MUST be replicated. Q24 CI drift test catches divergence
once it's wired (tests/test_cross_schema_drift.py in this service).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_login", "login", unique=True),
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_user_code", "user_code", unique=True),
        Index("ix_users_status", "status"),
        Index("ix_users_created_at", "created_at"),
        Index("ix_users_deleted_at", "deleted_at"),
        Index("ix_users_vendor_id", "vendor_id"),
        {"schema": "users"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # Doc-25: human-readable code separate from the UUID
    user_code: Mapped[Optional[str]] = mapped_column(String(16))
    login: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(64))
    last_name: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")

    # Cross-schema logical FK to masters.vendors.id (no DB-level constraint).
    vendor_id: Mapped[Optional[str]] = mapped_column(String(36))
    # Logical reference to masters.divisions.code (no DB-level constraint).
    division: Mapped[Optional[str]] = mapped_column(String(64))
    division_other: Mapped[Optional[str]] = mapped_column(String(255))

    phone_number: Mapped[Optional[str]] = mapped_column(String(32))
    # Doc-45 FE-label cache (e.g. "Org Admin", "Project Member")
    org_role: Mapped[Optional[str]] = mapped_column(String(64))

    # Refresh-token rotation (Doc-33+)
    refresh_token_jti: Mapped[Optional[str]] = mapped_column(String(36))
    previous_refresh_token_jti: Mapped[Optional[str]] = mapped_column(String(36))
    previous_refresh_token_jti_valid_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Soft-delete. deleted_by is a self-FK to users.id (within same schema).
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.users.id", use_alter=True, name="fk_users_deleted_by"),
    )
