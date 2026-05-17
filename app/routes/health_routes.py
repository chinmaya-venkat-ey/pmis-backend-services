"""GET /health, /ready, / — liveness/readiness probes + service info.

Mounted at the app root (no service prefix), per Decision 8d. Orchestrator
hits /health (process-alive, no DB) and /ready (DB ping). nginx forwards
externally as /health/notification, /ready/notification (illustrative
config in nginx/conf.d/pmis.conf).

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\routes\\health_routes.py:1-16
with the new /ready endpoint (Q16: no boot-time DDL means readiness must
include a DB ping).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.schemas.common import HealthResponse, ReadyResponse


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
    description="Process-alive check. No DB query. Returns 200 as long as the process responds.",
)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version="0.1.0",
    )


@router.get(
    "/ready",
    response_model=ReadyResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
    description=(
        "Includes a `SELECT 1` against the shared Postgres so the orchestrator "
        "knows the service can serve traffic. Returns 200 when DB is reachable, "
        "503 otherwise."
    ),
    responses={
        503: {"description": "DB unreachable"},
    },
)
def ready(db: Session = Depends(get_db)) -> ReadyResponse:
    try:
        db.execute(text("SELECT 1"))
        return ReadyResponse(status="ready", service=settings.service_name, db="ok")
    except Exception as exc:  # surface as 503
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"DB unreachable: {exc}",
        )
