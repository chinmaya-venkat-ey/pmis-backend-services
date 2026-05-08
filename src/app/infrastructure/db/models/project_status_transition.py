"""Project status transition master.

A row per legal ``(from_status, to_status)`` edge in the project lifecycle.
Replaces the in-code constants in ``app.api.v3.projects.services.transitions``
as the source of truth — those constants now seed this table on first boot.

Why a table:
- The frontend can query the legal next-statuses for a given project in one
  call (``GET /project_status_transitions``) instead of duplicating the rules.
- Ops can edit the rules without a code change (e.g. allow MEMBER to publish
  for a hackathon, by toggling ``requires_admin``).
- The `status` value sent in any request can be validated against
  the catalog: the route returns ``invalid_status`` when no row matches.

Schema:
- ``id``                : auto-increment surrogate.
- ``from_status``       : NULL means this row is the seed for the initial
                          status (no predecessor required); typically used
                          for the row marking "new" as a valid initial value.
- ``to_status``         : the destination status the system permits.
- ``requires_admin``    : if true, the actor must be an admin to take this
                          edge. Mirrors ADMIN_ONLY_TRANSITIONS in code.
- ``active``            : flips a row off without deleting it (history-safe).
- ``description``       : free-text description of the rule for docs/UI.

Unique constraint on ``(from_status, to_status)`` so we never have two
contradictory rules for the same edge.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Index, Integer, String, UniqueConstraint,
)

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ProjectStatusTransitionModel(Base):
    __tablename__ = "project_status_transitions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # NULL ``from_status`` represents the initial-status seed (status the
    # system accepts on a fresh create). For real edges, both columns are
    # required.
    from_status = Column(String(50), nullable=True, index=True)
    to_status = Column(String(50), nullable=False, index=True)

    requires_admin = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)

    description = Column(String(500), nullable=True)

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "from_status", "to_status",
            name="uq_project_status_transitions_edge",
        ),
        Index("idx_pst_to_status_active", "to_status", "active"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectStatusTransitionModel("
            f"{self.from_status} -> {self.to_status}, "
            f"admin={self.requires_admin})>"
        )
