"""Resource type catalog (RFP / ASG / CCN / ...).

Referenced from ``activity_resources.type_of_resource_id`` when an activity
is a resource-type activity in `details` mode. Seeded at startup with the
three well-known values; admins can add more via the /resource_types API.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Index, String
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ResourceTypeModel(Base):
    __tablename__ = "resource_types"

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid4()),
    )
    # Short canonical code: "rfp", "asg", "ccn", etc. Lowercase, unique.
    code = Column(String(50), nullable=False, unique=True, index=True)
    # Human-readable display name. The seeded built-ins use the short
    # uppercase form ("RFP", "ASG", "CCN") to match the FE dropdown
    # spec; admin-created entries can be any free-text label.
    name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        Index("idx_resource_types_active_code", "active", "code"),
    )

    def __repr__(self) -> str:
        return f"<ResourceTypeModel(id='{self.id}', code='{self.code}')>"
