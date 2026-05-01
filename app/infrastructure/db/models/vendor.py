"""Vendor SQLAlchemy model.

Catalog table that backs the project + milestone vendor-picker. Carries
the contact details the FE shows on Vendor Management screens — name,
description, email, contact-person, phone — plus soft-delete metadata.

Soft-delete columns (`deleted_at`, `deleted_by`) were added in doc 17 so
``DELETE /vendors/{id}`` can hide a vendor from the catalog without
losing the historical project/milestone mappings. Restore by clearing
``deleted_at`` and flipping ``active`` back on.

Contact columns (`email`, `contact_person`, `phone_number`) were added
in doc 18. All three are nullable — vendors created before this batch
keep their NULLs and the FE renders an empty cell for missing values.
Email is loosely validated (via the schema layer) but not strictly
unique — multiple vendors at the same parent org may share an
@example.com inbox.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class VendorModel(Base):
    __tablename__ = "vendors"

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid4()),
    )
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True, nullable=False, index=True)

    # Contact details (added in doc 18). All three nullable — pre-existing
    # vendors stay NULL until edited.
    email = Column(String(255), nullable=True, index=True)
    contact_person = Column(String(255), nullable=True)
    phone_number = Column(String(50), nullable=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Soft-delete. A non-NULL deleted_at hides the vendor from the catalog
    # endpoint and from picker validation, but the project_vendors /
    # milestone_vendors mapping rows are intentionally NOT touched.
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_vendors_active_name", "active", "name"),
        Index("idx_vendors_created_at", "created_at"),
        Index("idx_vendors_deleted_at", "deleted_at"),
        Index("idx_vendors_email", "email"),
    )

    def __repr__(self) -> str:
        return (
            f"<VendorModel(id='{self.id}', name='{self.name}', "
            f"active={self.active}, deleted_at={self.deleted_at})>"
        )
