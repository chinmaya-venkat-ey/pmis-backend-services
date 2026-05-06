"""Central v3 router — owns /api/v3/users/*, /api/v3/roles/*,
/api/v3/permissions/*, and /api/v3/master/* (user-mgmt slim slice).

Doc 37 part 2: brought to monolith parity. The master/* surface here
is the user-management slim slice (roles, permissions,
notification_templates). Other master-data slices (divisions, vendors,
project_categories, etc.) stay on the monolith.
"""
from fastapi import APIRouter

from .v3.master_data import router as master_data_router
from .v3.permissions import permissions_router
from .v3.roles import router as roles_router
from .v3.users import router as users_router


api_v3_router = APIRouter(prefix="/api/v3")
api_v3_router.include_router(users_router)
api_v3_router.include_router(roles_router)
api_v3_router.include_router(permissions_router)
api_v3_router.include_router(master_data_router)
