"""SlaAttachmentRepository — DB access for sla_attachments rows."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sla_attachment import SlaAttachment


class SlaAttachmentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- writes

    def create(self, row: SlaAttachment) -> SlaAttachment:
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def update_url(self, row: SlaAttachment, fresh_url: str) -> SlaAttachment:
        """Persist a refreshed download URL after a refresh-url round-trip."""
        row.file_url = fresh_url
        self.db.flush()
        return row

    def update_caption(
        self, row: SlaAttachment, caption: Optional[str],
    ) -> SlaAttachment:
        row.caption = caption
        self.db.flush()
        return row

    def soft_delete(self, row: SlaAttachment) -> SlaAttachment:
        row.deleted_at = datetime.now(timezone.utc)
        self.db.flush()
        return row

    # ---------------------------------------------------------------- reads

    def get_by_id(self, attachment_id: str) -> Optional[SlaAttachment]:
        # Tombstones are intentionally returned here so callers can
        # detect "already deleted" rather than 404. The route layer
        # filters by deleted_at when needed.
        return self.db.execute(
            select(SlaAttachment).where(SlaAttachment.id == attachment_id)
        ).scalar_one_or_none()

    def list_for_sla(self, sla_id: str) -> List[SlaAttachment]:
        """Live attachments for an SLA, oldest-first.

        Newest-first would force the FE to reverse before render; oldest-
        first matches insertion order, which mirrors how users uploaded
        and is what the gallery wants left-to-right.
        """
        stmt = (
            select(SlaAttachment)
            .where(
                SlaAttachment.sla_id == sla_id,
                SlaAttachment.deleted_at.is_(None),
            )
            .order_by(SlaAttachment.uploaded_at)
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_for_sla(self, sla_id: str) -> int:
        from sqlalchemy import func
        stmt = (
            select(func.count())
            .select_from(SlaAttachment)
            .where(
                SlaAttachment.sla_id == sla_id,
                SlaAttachment.deleted_at.is_(None),
            )
        )
        return int(self.db.execute(stmt).scalar() or 0)
