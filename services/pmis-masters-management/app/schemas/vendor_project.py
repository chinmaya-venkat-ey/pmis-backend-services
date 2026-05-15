"""Pydantic v2 response schema for /masters/vendors/{vendor_id}/projects/list.

Returns a slim view of the projects mapped to a vendor — id, code, name, status.
Full project metadata is served by pmis-project-management; masters-svc only
exposes the cross-schema-joined slim list as a convenience for the vendor
detail page.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class VendorProjectSummary(BaseModel):
    """One project mapped to a vendor — slim shape only."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Project UUID")
    project_code: Optional[str] = Field(default=None, description="Human-readable code")
    name: str = Field(..., description="Project name")
    status: str = Field(..., description="Project lifecycle status")
