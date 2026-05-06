"""Database models package — imports every model so Base.metadata sees them.

Alembic's ``target_metadata = Base.metadata`` needs every model class
imported somewhere before ``alembic revision --autogenerate`` runs.
This package's ``__init__`` is that import hook.

Covers user-mgmt's owned tables (users / RBAC / 2FA / notification
audit log) plus read-only mirrors of vendors and projects so:
  - in-memory SQLite test DBs can satisfy FKs from users / project_members;
  - create / update flows can validate against vendors + projects
    without HTTP round-trips.

The notification template catalog itself moved to
PMIS-notification-service (doc 38), so there's no model for it here.
"""
from .project import ProjectModel
from .project_member import ProjectMemberModel
from .revoked_token import RevokedTokenModel
from .role import RoleModel
from .user import UserModel
from .vendor import VendorModel
# Doc 21B RBAC tables.
from .permission import PermissionModel
from .role_permission import RolePermissionModel
from .user_role import UserRoleModel
from .user_permission import UserPermissionModel
# 2FA + password reset + notification audit log (notification_log
# stays here — it's user-mgmt's own audit table; templates moved to
# PMIS-notification-service per doc 38).
from .notification_log import NotificationLogModel
from .otp_code import OtpCodeModel
from .password_reset_token import PasswordResetTokenModel

__all__ = [
    "ProjectMemberModel",
    "ProjectModel",
    "RevokedTokenModel",
    "RoleModel",
    "UserModel",
    "VendorModel",
    "PermissionModel", "RolePermissionModel",
    "UserRoleModel", "UserPermissionModel",
    "NotificationLogModel", "OtpCodeModel", "PasswordResetTokenModel",
]
