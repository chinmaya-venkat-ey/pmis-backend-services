"""ApprovalInboxController — thin orchestration over ApprovalInboxService."""
from __future__ import annotations

from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.schemas.approval_inbox import (
    InboxDetailResponse,
    InboxListResponse,
    TransitionRequest,
)
from app.services.approval_inbox_service import ApprovalInboxService


class ApprovalInboxController:
    def __init__(self, db: Session):
        self.service = ApprovalInboxService(db)

    def list_inbox(
        self,
        request: Request,
        *,
        role: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> InboxListResponse:
        return self.service.list_inbox(
            request, role=role, status=status, search=search,
        )

    def get_detail(self, request: Request, business_id: str) -> InboxDetailResponse:
        return self.service.get_detail(request, business_id)

    def transition(
        self,
        request: Request,
        business_id: str,
        payload: TransitionRequest,
    ) -> InboxDetailResponse:
        return self.service.transition(request, business_id, payload)
