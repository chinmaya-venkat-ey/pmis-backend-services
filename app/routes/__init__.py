"""Notification-svc API router composition.

Exposes a single `api_router` mounted at `/notification` in main.py.
Health routes are mounted at the app root (outside the prefix) per
Decision 8d.

Routes (per PLAN.md §2.4):
  POST /notification/email/send
  POST /notification/sms/send
  POST /notification/dispatch                  (Doc-38 canonical)
  POST /notification/cron/daily-digest         (X-Cron-Secret)

Dropped per Q13 (OTP storage moved to user-svc):
  POST /notification/otp/send
  POST /notification/otp/verify
"""
from __future__ import annotations

from fastapi import APIRouter

from app.routes.cron_routes import router as cron_router
from app.routes.dispatch_routes import router as dispatch_router
from app.routes.email_routes import router as email_router
from app.routes.sms_routes import router as sms_router


api_router = APIRouter(prefix="/notification")
api_router.include_router(email_router)
api_router.include_router(sms_router)
api_router.include_router(dispatch_router)
api_router.include_router(cron_router)
