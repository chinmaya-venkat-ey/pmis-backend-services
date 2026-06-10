"""SlaAttachmentService — orchestrates uploads/lists/deletes/refreshes.

Talks to two surfaces:
  * ``SlaRepository``                — verify the SLA exists / not deleted
  * ``SlaAttachmentRepository``      — persist the row
  * ``FileStoreClient`` (pmis-file-store) — actually hold the bytes
"""
from __future__ import annotations

from typing import Any, BinaryIO, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.clients import (
    AnyFileClient,
    FileStoreUnavailable,
    RefreshedUrl,
)
from app.core.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.models.sla_attachment import SlaAttachment
from app.repositories.sla_attachment_repository import SlaAttachmentRepository
from app.repositories.sla_repository import SlaRepository
from app.schemas.sla_attachment import (
    ALLOWED_IMAGE_MIMES,
    SlaAttachmentResponse,
    SlaAttachmentRefreshResponse,
)


# Hard cap on per-file size — anything above is rejected before forwarding
# to filestore. 10 MB is generous for screenshots / scans but rules out
# someone uploading a 4K video by accident.
_MAX_BYTES = 10 * 1024 * 1024


class SlaAttachmentService:
    def __init__(
        self,
        db: Session,
        file_store_client: Optional[AnyFileClient] = None,
    ):
        self.db = db
        self.repo = SlaAttachmentRepository(db)
        self.sla_repo = SlaRepository(db)
        self.file_store = file_store_client

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _to_response(row: SlaAttachment) -> SlaAttachmentResponse:
        return SlaAttachmentResponse(
            id=row.id,
            sla_id=row.sla_id,
            file_id=row.file_id,
            file_url=row.file_url,
            original_filename=row.original_filename,
            mime_type=row.mime_type,
            size_bytes=row.size_bytes,
            caption=row.caption,
            uploaded_by=row.uploaded_by,
            uploaded_at=row.uploaded_at,
        )

    def _require_live_sla(self, sla_id: str):
        sla = self.sla_repo.get_by_id(sla_id)
        if sla is None:
            raise NotFoundError(
                f"SLA '{sla_id}' not found", code="sla_not_found",
            )
        if sla.status == "DELETED":
            raise ConflictError(
                f"SLA '{sla.sla_ref}' is deleted; cannot attach files",
                code="sla_deleted",
            )
        return sla

    # ---------------------------------------------------------------- upload

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
        sla = self._require_live_sla(sla_id)

        # 1. MIME validation. The form only offers image/* so the UI
        # filters most files, but a curl caller could send anything.
        if (mime_type or "").lower() not in ALLOWED_IMAGE_MIMES:
            raise ValidationError(
                f"Unsupported file type '{mime_type}'. Only PNG, JPEG, "
                f"WebP and GIF images are accepted.",
                code="unsupported_mime",
            )

        # 2. Size cap. Saves us from forwarding huge bytes to filestore
        # just to have it 413 there.
        if size_bytes > _MAX_BYTES:
            raise ValidationError(
                f"File too large: {size_bytes} bytes (max {_MAX_BYTES}).",
                code="file_too_large",
            )

        if self.file_store is None:
            # Service was constructed without a configured filestore —
            # surface a 503-ish error rather than crashing inside .upload().
            raise FileStoreUnavailable(
                "FILE_STORE_SERVICE_URL not configured on contract-management",
            )

        # 3. Forward bytes to pmis-file-store. The SLA's sla_ref is sent
        # as the entity_id so filestore can show "owned by PMU-SLA010" in
        # its admin view; entity_type identifies us as the source service.
        stored = self.file_store.upload(
            file_obj,
            filename or "attachment",
            mime_type,
            entity_type="contract.sla",
            entity_id=sla.sla_ref,
            bearer_token=bearer_token,
        )

        # 4. Persist the local row pointing at the filestore handle.
        row = SlaAttachment(
            id=str(uuid4()),
            sla_id=sla_id,
            file_id=stored.file_id,
            file_url=stored.download_url,
            original_filename=stored.original_filename or filename,
            mime_type=stored.mime_type or mime_type,
            size_bytes=stored.size_bytes,
            caption=caption,
            uploaded_by=uploaded_by,
        )
        row = self.repo.create(row)
        return self._to_response(row)

    # ---------------------------------------------------------------- list / get

    def list_for_sla(self, sla_id: str) -> List[SlaAttachmentResponse]:
        # Don't require the SLA to exist here — listing on a deleted
        # SLA returns an empty list, which is what the audit view wants.
        return [self._to_response(r) for r in self.repo.list_for_sla(sla_id)]

    def get(self, attachment_id: str) -> SlaAttachmentResponse:
        row = self.repo.get_by_id(attachment_id)
        if row is None or row.deleted_at is not None:
            raise NotFoundError(
                f"Attachment '{attachment_id}' not found",
                code="attachment_not_found",
            )
        return self._to_response(row)

    # ---------------------------------------------------------------- refresh URL

    def refresh_url(
        self,
        attachment_id: str,
        bearer_token: Optional[str] = None,
    ) -> SlaAttachmentRefreshResponse:
        row = self.repo.get_by_id(attachment_id)
        if row is None or row.deleted_at is not None:
            raise NotFoundError(
                f"Attachment '{attachment_id}' not found",
                code="attachment_not_found",
            )
        if self.file_store is None:
            raise FileStoreUnavailable(
                "FILE_STORE_SERVICE_URL not configured on contract-management",
            )
        fresh: RefreshedUrl = self.file_store.refresh_url(
            row.file_id, bearer_token=bearer_token,
        )
        if fresh.download_url:
            self.repo.update_url(row, fresh.download_url)
        return SlaAttachmentRefreshResponse(
            id=row.id,
            file_url=fresh.download_url or row.file_url,
            expires_in_seconds=fresh.expires_in_seconds,
        )

    # ---------------------------------------------------------------- caption

    def update_caption(
        self, attachment_id: str, caption: Optional[str],
    ) -> SlaAttachmentResponse:
        row = self.repo.get_by_id(attachment_id)
        if row is None or row.deleted_at is not None:
            raise NotFoundError(
                f"Attachment '{attachment_id}' not found",
                code="attachment_not_found",
            )
        row = self.repo.update_caption(row, caption)
        return self._to_response(row)

    # ---------------------------------------------------------------- delete

    def delete(
        self, attachment_id: str, bearer_token: Optional[str] = None,
    ) -> dict[str, Any]:
        row = self.repo.get_by_id(attachment_id)
        if row is None or row.deleted_at is not None:
            raise NotFoundError(
                f"Attachment '{attachment_id}' not found",
                code="attachment_not_found",
            )
        # Soft-delete our row first so the FE's optimistic update sticks.
        # Then best-effort soft-delete the file in pmis-file-store. A
        # filestore failure does NOT undo our delete — the orphan
        # filestore row is cheap; the alternative is a partially-deleted
        # state that's harder to reason about.
        self.repo.soft_delete(row)
        filestore_removed = False
        if self.file_store is not None:
            try:
                filestore_removed = self.file_store.delete(
                    row.file_id, bearer_token=bearer_token,
                )
            except FileStoreUnavailable:
                filestore_removed = False
        return {
            "id": row.id,
            "filestore_removed": filestore_removed,
        }
