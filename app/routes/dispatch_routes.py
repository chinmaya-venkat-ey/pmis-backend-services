"""POST /notification/dispatch — templated dispatch (Doc-38 canonical).

Single-call alternative to fetching a template + rendering + calling
/email/send or /sms/send. Used by user-svc's auth flows (OTP, password
reset) so they never host a template renderer.

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\routes\\dispatch_routes.py:1-67
with service-layer extraction per Q8 (DispatchService instead of inline
route logic).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.controllers.dispatch_controller import DispatchController
from app.dependencies import get_dispatch_controller
from app.schemas.dispatch import DispatchRequest, DispatchResponse


router = APIRouter(tags=["dispatch"])


@router.post(
    "/dispatch",
    response_model=DispatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Render a template and dispatch via the configured provider",
    description=(
        "Single canonical endpoint for templated notifications. Looks up the "
        "active row in masters.notification_templates by (template_kind, "
        "channel), renders it with the caller's payload, and dispatches via "
        "the configured provider. Trust-boundary internal (no JWT)."
    ),
)
def dispatch_templated(
    payload: DispatchRequest,
    controller: Annotated[DispatchController, Depends(get_dispatch_controller)],
) -> DispatchResponse:
    return controller.dispatch(payload)
