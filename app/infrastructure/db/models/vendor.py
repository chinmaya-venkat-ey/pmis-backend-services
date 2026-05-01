"""Vendor SQLAlchemy mapping — owned by project-service / monolith.

This service does NOT manage vendors (no CRUD endpoints), but it needs
a mapping for two reasons:

  1. ``users.vendor_id`` FK references this table; create_all in tests
     needs the referenced table present in metadata.
  2. The user-create / user-update flows query this table to validate
     that the supplied ``vendorId`` exists and is not soft-deleted.

Schema mirrors the monolith / project-service definition exactly so a
shared-Postgres setup keeps both services in sync. Don't add columns
here without coordinating with the project-service.
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

    # Contact details (added in monolith doc 18). All nullable.
    email = Column(String(255), nullable=True, index=True)
    contact_person = Column(String(255), nullable=True)
    phone_number = Column(String(50), nullable=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Soft-delete. Mirrors monolith semantics — non-NULL deleted_at hides
    # the vendor from picker validation. Mapping rows untouched.
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)

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
