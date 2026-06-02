"""Discussion-feed schemas — wire surface for
``GET /project/projects/{uuid}/discussion-feed``.

Each row carries the comment metadata plus the target entity's name so
the FE can render which milestone / activity / task / subtask the comment
belongs to without a per-id round-trip.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DiscussionFeedEntry(BaseModel):
    """One row in the unified discussion feed."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    target_kind: str
    target_id: str
    target_name: Optional[str] = None
    body: Optional[str] = None
    attachments: List[Any] = Field(default_factory=list)
    created_at: datetime
    created_by: Optional[str] = None


class DiscussionFeedProjectInfo(BaseModel):
    """Project header on the feed payload."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    name: str


class DiscussionFeedResponse(BaseModel):
    """``GET /project/projects/{uuid}/discussion-feed`` payload."""

    model_config = ConfigDict(from_attributes=False)

    project: DiscussionFeedProjectInfo
    total: int
    offset: int
    page_size: int
    elements: List[DiscussionFeedEntry] = Field(default_factory=list)
