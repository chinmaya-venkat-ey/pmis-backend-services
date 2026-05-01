"""Database models package — imports every model so Base.metadata sees them.

Alembic's ``target_metadata = Base.metadata`` needs every model class
imported somewhere before ``alembic revision --autogenerate`` runs.
This package's ``__init__`` is that import hook.

Vendor / Project / ProjectMember are mapped here even though
project-service / monolith owns their writes — see each file's
docstring. They're needed so:
  - in-memory SQLite test DBs can satisfy users.vendor_id /
    project_members.user_id FKs;
  - this service's create / update flows can validate against vendors
    + projects without HTTP round-trips.
"""
from .project import ProjectModel
from .project_member import ProjectMemberModel
from .revoked_token import RevokedTokenModel
from .role import RoleModel
from .user import UserModel
from .vendor import VendorModel

__all__ = [
    "ProjectMemberModel",
    "ProjectModel",
    "RevokedTokenModel",
    "RoleModel",
    "UserModel",
    "VendorModel",
]
