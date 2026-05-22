"""Route composition for pmis-file-store."""
from fastapi import APIRouter

from app.routes import audit_routes, file_routes

files_router = APIRouter(prefix="/api/v3")
files_router.include_router(file_routes.router)
files_router.include_router(audit_routes.router)
