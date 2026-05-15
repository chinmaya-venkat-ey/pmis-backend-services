"""GET /health, /ready — mounted at app root (outside /user prefix)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
    description="Process-alive check. No DB query.",
)
def health() -> dict:
    return {"status": "ok", "service": settings.service_name, "version": "0.1.0"}


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness probe (DB ping)",
    responses={503: {"description": "DB unreachable"}},
)
def ready(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "service": settings.service_name, "db": "ok"}
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"DB unreachable: {exc}",
        )
