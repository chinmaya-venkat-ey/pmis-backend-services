"""FastAPI dependency providers (DI).

Centralizes Depends(...) factories so routes don't repeat the wiring.
Each `get_<X>_controller` builds a controller with its service + DB.

Ported pattern from
  C:\\Programming\\PMIS\\PMIS-notification-service\\app\\routes\\email_routes.py:10-11
(where `get_controller` was inlined per-route). Centralized here for clarity.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.controllers.cron_controller import CronController
from app.controllers.dispatch_controller import DispatchController
from app.controllers.email_controller import EmailController
from app.controllers.sms_controller import SMSController
from app.db import get_db
from app.services.digest_service import DigestService
from app.services.dispatch_service import DispatchService
from app.services.email_service import EmailService, get_email_service
from app.services.sms_service import SMSService, get_sms_service


def get_email_controller(
    service: EmailService = Depends(get_email_service),
) -> EmailController:
    return EmailController(service)


def get_sms_controller(
    service: SMSService = Depends(get_sms_service),
) -> SMSController:
    return SMSController(service)


def get_dispatch_controller(
    db: Session = Depends(get_db),
    email_service: EmailService = Depends(get_email_service),
    sms_service: SMSService = Depends(get_sms_service),
) -> DispatchController:
    return DispatchController(DispatchService(db, email_service, sms_service))


def get_cron_controller(
    db: Session = Depends(get_db),
    email_service: EmailService = Depends(get_email_service),
) -> CronController:
    return CronController(DigestService(db, email_service))
