"""Central v3 router — this service only owns /api/v3/users/*."""
from fastapi import APIRouter

from .v3.users import router as users_router


api_v3_router = APIRouter(prefix="/api/v3")
api_v3_router.include_router(users_router)
