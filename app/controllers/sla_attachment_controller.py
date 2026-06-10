"""Thin controller — composes service deps and exposes the same shape
the routes use."""
from __future__ import annotations

from typing import Any, BinaryIO, List, Optional

from sqlalchemy.orm import Session

from app.clients import FileStoreClient
from app.schemas.sla_attachment import (
    SlaAttachmentRefreshResponse,
    SlaAttachmentResponse,
)
from app.services.sla_attachment_service import SlaAttachmentService


class SlaAttachmentController:
    def __init__(
        self,
        db: Session,
        file_store_client: Optional[FileStoreClient] = None,
    ):
        self.service = SlaAttachmentService(
            db, file_store_client=file_store_client,
        )

    def upload(
        self,
        sla_id: str,
        *,
        file_obj: BinaryIO,
        filename: str,
        mime_type: str,
        size_bytes: int,
        caption: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ) -> SlaAttachmentResponse:
        return self.service.upload(
            sla_id,
            file_obj=file_obj,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            caption=caption,
            uploaded_by=uploaded_by,
            bearer_token=bearer_token,
        )

    def list_for_sla(self, sla_id: str) -> List[SlaAttachmentResponse]:
        return self.service.list_for_sla(sla_id)

    def get(self, attachment_id: str) -> SlaAttachmentResponse:
        return self.service.get(attachment_id)

    def refresh_url(
        self, attachment_id: str, bearer_token: Optional[str] = None,
    ) -> SlaAttachmentRefreshResponse:
        return self.service.refresh_url(
            attachment_id, bearer_token=bearer_token,
        )

    def update_caption(
        self, attachment_id: str, caption: Optional[str],
    ) -> SlaAttachmentResponse:
        return self.service.update_caption(attachment_id, caption)

    def delete(
        self, attachment_id: str, bearer_token: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.service.delete(
            attachment_id, bearer_token=bearer_token,
        )
