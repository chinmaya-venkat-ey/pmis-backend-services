"""DispatchController — HTTP adapter for /notification/dispatch.

Wraps DispatchService (template render + provider send) for the route layer.
"""
from __future__ import annotations

from app.schemas.dispatch import DispatchRequest, DispatchResponse
from app.services.dispatch_service import DispatchService


class DispatchController:
    def __init__(self, service: DispatchService):
        self.service = service

    def dispatch(self, payload: DispatchRequest) -> DispatchResponse:
        result = self.service.dispatch(
            channel=payload.channel,
            recipient=payload.recipient,
            template_kind=payload.template_kind,
            payload=payload.payload,
        )
        return DispatchResponse(**result)
