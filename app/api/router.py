"""Central v3 router — owns /api/v3/users/* and /api/v3/roles/*."""
from fastapi import APIRouter

from .v3.roles import router as roles_router
from .v3.users import router as users_router


api_v3_router = APIRouter(prefix="/api/v3")
api_v3_router.include_router(users_router)
api_v3_router.include_router(roles_router)
