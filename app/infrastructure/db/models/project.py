"""
Project database model.

`id` is a UUID string (VARCHAR(36)) — the public handle exposed in URLs and
response bodies. Server-generated via uuid4 on insert. Never changes once
assigned.

`project_code` is an additional human-readable unique handle
(UIDAI-PRYYMMDDHHMMSS in IST), also server-generated.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Index, ForeignKey, Text, text
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ProjectModel(Base):
    """Project database model."""

    __tablename__ = "projects"

    # UUID primary key. No separate "uuid" column — `id` itself is the UUID.
    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid4()),
    )

    # Human-readable code: UIDAI-PRYYMMDDHHMMSS (IST timezone).
    # Server-generated on create; fresh code on every version.
    project_code = Column(String(30), unique=True, nullable=False, index=True)

    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    public = Column(Boolean, default=False, nullable=False)
    status_explanation = Column(Text, nullable=True)

    # Self-FKs — all must match the new String(36) id type.
    parent_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    version_of = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    baseline_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    version_no = Column(Integer, nullable=True)

    # Status: lowercase values. Allowed: new, draft, published, closed, suspended.
    status = Column(String(50), default="new", nullable=False, index=True)
    # Owner is a division code: 'tmd1' / 'tmd2' / 'others'. Stored
    # lowercase. When `owner == 'others'` the FE captures a free-text
    # label and supplies it as `ownerOther`; that value lands in
    # ``owner_other`` below. NULL on baselines whose owner was set
    # before this column existed (auto-healed via the SQLite drift pass).
    owner = Column(String(255), nullable=True, index=True)
    owner_other = Column(String(255), nullable=True)
    # Category: MSAP, MSIP, BSP, or 'others'. Immutable after create.
    category = Column(String(50), nullable=True, index=True)
    # When category == 'others', a free-text label is required and stored here.
    # NULL for all other categories.
    category_other = Column(String(255), nullable=True)
    # Reason text explaining why 'others' was chosen instead of an existing
    # category (MSAP/MSIP/BSP). Required when category == 'others'; NULL
    # otherwise. Captured for governance / category-curation review.
    category_other_reason = Column(String(1000), nullable=True)
    start_date = Column(DateTime, nullable=True, index=True)
    end_date = Column(DateTime, nullable=True, index=True)
    # Actual dates — recorded when work actually begins / ends. Both are
    # version-only editable per project lifecycle rules; baselines leave
    # them NULL. Mirrors the design's "Actual Start Date" / "Actual End
    # Date" fields on the project details panel.
    actual_start_date = Column(DateTime, nullable=True)
    actual_end_date = Column(DateTime, nullable=True)

    # Versioning marker.
    is_version = Column(Boolean, default=False, nullable=False, index=True)

    # Audit + soft delete. users.id is still INTEGER, so these stay Integer.
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Enforces "one active version per baseline" at the DB layer.
    # Active = is_version AND status != 'suspended' AND not soft-deleted.
    __table_args__ = (
        Index("idx_projects_project_code", "project_code"),
        Index("idx_projects_name", "name"),
        Index("idx_projects_active", "active"),
        Index("idx_projects_public", "public"),
        Index("idx_projects_parent_id", "parent_id"),
        Index("idx_projects_status", "status"),
        Index("idx_projects_owner", "owner"),
        Index("idx_projects_category", "category"),
        Index("idx_projects_start_date", "start_date"),
        Index("idx_projects_end_date", "end_date"),
        Index("idx_projects_is_version", "is_version"),
        Index("idx_projects_version_of", "version_of"),
        Index("idx_projects_baseline_id", "baseline_id"),
        Index("idx_projects_deleted_at", "deleted_at"),
        Index(
            "ux_projects_active_version_per_baseline",
            "version_of",
            unique=True,
            sqlite_where=text("is_version = 1 AND status != 'suspended' AND deleted_at IS NULL"),
            postgresql_where=text("is_version = true AND status != 'suspended' AND deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectModel(id='{self.id}', "
            f"project_code='{self.project_code}', name='{self.name}', "
            f"status='{self.status}', is_version={self.is_version})>"
        )
