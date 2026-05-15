"""NotificationTemplateController — HTTP adapter for /masters/notification-templates/* routes."""
from __future__ import annotations

from typing import List

from app.schemas.notification_template import (
    NotificationTemplateCreateRequest,
    NotificationTemplateResponse,
    NotificationTemplateUpdateRequest,
)
from app.services.notification_template_service import NotificationTemplateService


class NotificationTemplateController:
    def __init__(self, service: NotificationTemplateService):
        self.service = service

    def list_(
        self, *, include_inactive: bool = False
    ) -> List[NotificationTemplateResponse]:
        rows = self.service.list_(include_inactive=include_inactive)
        return [NotificationTemplateResponse.model_validate(r) for r in rows]

    def get_details(self, template_id: int) -> NotificationTemplateResponse:
        return NotificationTemplateResponse.model_validate(
            self.service.get_by_id(template_id)
        )

    def create(
        self, payload: NotificationTemplateCreateRequest
    ) -> NotificationTemplateResponse:
        return NotificationTemplateResponse.model_validate(
            self.service.create(payload)
        )

    def update(
        self,
        template_id: int,
        payload: NotificationTemplateUpdateRequest,
    ) -> NotificationTemplateResponse:
        return NotificationTemplateResponse.model_validate(
            self.service.update(template_id, payload)
        )

    def delete(self, template_id: int) -> NotificationTemplateResponse:
        return NotificationTemplateResponse.model_validate(
            self.service.delete(template_id)
        )

    def restore(self, template_id: int) -> NotificationTemplateResponse:
        return NotificationTemplateResponse.model_validate(
            self.service.restore(template_id)
        )
