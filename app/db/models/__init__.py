"""Database models package.

Covers this service's owned tables (``notification_templates``) plus
read-only mirrors of monolith / user-service tables that the daily-
digest cron queries against (projects, milestones, activities, users,
roles, user_role_assignments, project_vendors). In shared-DB deploys
the mirrors map to existing rows monolith populated; for in-memory
SQLite test DBs ``Base.metadata.create_all`` builds the columns the
cron reads.
"""
from .activity import ActivityModel
from .milestone import MilestoneModel
from .notification_template import NotificationTemplateModel
from .project import ProjectModel
from .project_vendor import ProjectVendorModel
from .role import RoleModel
from .user import UserModel
from .user_role_assignment import UserRoleAssignmentModel

__all__ = [
    "ActivityModel",
    "MilestoneModel",
    "NotificationTemplateModel",
    "ProjectModel",
    "ProjectVendorModel",
    "RoleModel",
    "UserModel",
    "UserRoleAssignmentModel",
]
