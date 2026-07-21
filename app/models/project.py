"""Project SQLAlchemy model — owned by pmis-project-management (schema `project`).

UUID PK. `project_code` is the human-readable secondary key (UIDAI-PRYYMMDDHHMMSS
in IST, server-generated). Self-FK on `parent_id` for project hierarchy.

Status values: 'new' | 'draft' | 'published' | 'closed'. Transitions are
governed by the `masters.project_status_transitions` catalog (read cross-schema).

Soft-delete via `deleted_at` + `deleted_by`. `created_by` / `updated_by` /
`deleted_by` are logical-only FKs to `users.users.id` (cross-schema; not
enforced at the DB level).

WARNING: mirrored read-only in other services'
`app/models/_cross_schema.py`. Schema changes here must be replicated.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_project_code", "project_code", unique=True),
        Index("ix_projects_name", "name"),
        # Bug #141: project names must be unique among LIVE rows.
        # Soft-deleted rows free their name. Materialized by
        # alembic p1a000000009.
        Index(
            "uq_projects_name_live",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_projects_active", "active"),
        Index("ix_projects_public", "public"),
        Index("ix_projects_parent_id", "parent_id"),
        Index("ix_projects_status", "status"),
        Index("ix_projects_owner", "owner"),
        Index("ix_projects_category", "category"),
        Index("ix_projects_start_date", "start_date"),
        Index("ix_projects_end_date", "end_date"),
        Index("ix_projects_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    public: Mapped[bool] = mapped_column(Boolean, default=False)
    status_explanation: Mapped[Optional[str]] = mapped_column(Text)

    # Self-FK for project hierarchy.
    parent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("project.projects.id", use_alter=True, name="fk_projects_parent_id"),
    )

    status: Mapped[str] = mapped_column(String(50), default="new")
    # Owner is a division code (logical FK to masters.divisions.code).
    owner: Mapped[Optional[str]] = mapped_column(String(255))
    # Category is logical FK to masters.project_categories.code.
    category: Mapped[Optional[str]] = mapped_column(String(50))
    category_other: Mapped[Optional[str]] = mapped_column(String(255))
    category_other_reason: Mapped[Optional[str]] = mapped_column(String(1000))

    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # #321 — the date the contract was signed (client requirement, captured at
    # project creation). Nullable/additive.
    contract_signing_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # #322 — reason/remarks for a late actual start, captured alongside the
    # actual start date (with optional attachments via the project attachment
    # path). Nullable/additive.
    actual_start_remarks: Mapped[Optional[str]] = mapped_column(String(2000))

    # Finance fields — INR rupees stored as NUMERIC(18, 2). All default to
    # safe zero/no-op values so existing rows continue to behave as before
    # the feature landed. ``total_project_value_excl_tax`` = 0 keeps the
    # CCN cap dormant (cap check is skipped service-side when TPV = 0);
    # set it > 0 to activate cap enforcement. ``tax_percent`` drives the
    # derived inclusive-tax companion returned on the wire — the inclusive
    # value is never stored. ``ccn_cap_percent`` defaults to 25 (the
    # standard contractual extension percentage).
    total_project_value_excl_tax: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False,
        server_default=text("0"), default=Decimal("0"),
    )
    tax_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False,
        server_default=text("0"), default=Decimal("0"),
    )
    ccn_cap_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False,
        server_default=text("25"), default=Decimal("25"),
    )
    # Project-level billing frequency for the payment screen — ONE per project
    # (applies to every phase's cycle counts + time-based carry-forward).
    # Logical FK to masters.frequencies.code. Null until set.
    payment_frequency_code: Mapped[Optional[str]] = mapped_column(String(32))

    # Project-specific config/checks bag — a free-form JSONB object of values
    # that are set per project (NOT driven by any master catalog): half-day
    # hours, attendance-captured flag, sandwich-leave flag, leaves-per-frequency,
    # prorated-leaves flag, etc. Grouped into ONE object so new checks can be
    # added without a schema migration. Shape is validated/documented by the
    # ``ProjectConfig`` Pydantic model (extra keys tolerated). Defaults to {}.
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict,
    )

    # Audit / soft-delete. user-id FKs are LOGICAL only (cross-schema).
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[Optional[str]] = mapped_column(String(36))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
