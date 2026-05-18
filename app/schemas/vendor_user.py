"""Pydantic v2 response schema for GET /masters/vendors/{vendor_id}/users.

Returns slim user summaries for all active users associated with a vendor.
Cross-schema read from users.users (read-only mirror).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class VendorUserSummary(BaseModel):
    """One user linked to a vendor — slim shape only."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="User UUID")
    user_code: Optional[str] = Field(default=None)
    login: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: str
