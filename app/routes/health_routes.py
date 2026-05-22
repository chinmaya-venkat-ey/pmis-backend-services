"""Health and readiness probes for pmis-file-store."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.utilities.s3_client import get_s3_client


router = APIRouter(tags=["health"])


@router.get("/health", include_in_schema=False)
async def health():
    return JSONResponse({"status": "ok", "service": "pmis-file-store"})


@router.get("/ready", include_in_schema=False)
async def ready():
    try:
        s3_ok = get_s3_client().health_check()
    except Exception:  # noqa: BLE001
        s3_ok = False

    if not s3_ok:
        return JSONResponse(
            {"status": "degraded", "s3": "unreachable"},
            status_code=503,
        )
    return JSONResponse({"status": "ok", "s3": "reachable"})
