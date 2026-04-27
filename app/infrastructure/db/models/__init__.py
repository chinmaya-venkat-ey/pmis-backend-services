"""Database models package — imports every model so Base.metadata sees them.

Alembic's ``target_metadata = Base.metadata`` needs every model class
imported somewhere before ``alembic revision --autogenerate`` runs.
This package's ``__init__`` is that import hook.
"""
from .user import UserModel
from .role import RoleModel
from .revoked_token import RevokedTokenModel

__all__ = ["UserModel", "RoleModel", "RevokedTokenModel"]
