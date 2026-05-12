"""Read-only mirror of the scoped-RBAC ``user_role_assignments`` table.

A row has exactly one of:
  - ``organization_id`` set   → org-scoped grant (e.g. org_admin of a vendor)
  - ``project_id`` set        → project-scoped grant (project_admin / member)
  - both NULL                 → global grant (super_admin / admin)

The daily-digest cron uses this to resolve "who should be notified
about events on project X" — see ``services/digest_service.py``.
"""
from sqlalchemy import Column, ForeignKey, Integer, String

from ..session import Base


class UserRoleAssignmentModel(Base):
    __tablename__ = "user_role_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(
        String(36), ForeignKey("users.id"), nullable=False, index=True,
    )
    role_id = Column(
        Integer, ForeignKey("roles.id"), nullable=False, index=True,
    )
    organization_id = Column(String(36), nullable=True, index=True)
    project_id = Column(
        String(36), ForeignKey("projects.id"), nullable=True, index=True,
    )
