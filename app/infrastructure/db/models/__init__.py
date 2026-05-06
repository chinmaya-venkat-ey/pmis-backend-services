"""Database models package — imports every model so Base.metadata sees them.

Alembic's ``target_metadata = Base.metadata`` needs every model class
imported somewhere before ``alembic revision --autogenerate`` runs.
This package's ``__init__`` is that import hook.

Doc 37 part 2 (initial port): brought model layer to parity with the
monolith. Adds the doc-21B RBAC tables (permissions / role_permissions
/ user_roles / user_permissions), doc-33-change-3 2FA + password-reset
+ notification-log tables, and doc-36 notification_templates table.

Vendor / Project / ProjectMember are mapped here even though
project-service / monolith owns their writes:
  - in-memory SQLite test DBs can satisfy users.vendor_id /
    project_members.user_id FKs;
  - this service's create / update flows can validate against vendors
    + projects without HTTP round-trips.

Routes / services / RBAC repository / proxy plumbing land in
follow-up commits — see planned_changes/37 in the monolith repo for
the migration runbook.
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
# Doc 33 change 3: 2FA + password reset + notification audit log.
from .notification_log import NotificationLogModel
from .otp_code import OtpCodeModel
from .password_reset_token import PasswordResetTokenModel
# Doc 36: DB-backed email + SMS template content.
from .notification_template import NotificationTemplateModel

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
    "NotificationTemplateModel",
]
