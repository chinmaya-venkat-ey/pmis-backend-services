"""Slim cross-resource response shapes for sub-listing endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserSummary(BaseModel):
    """Slim user shape — used by vendors→users sub-listing."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    user_code: Optional[str] = None
    login: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: str


class ProjectSummary(BaseModel):
    """Slim project shape — used by users→projects + vendors→projects sub-listing."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    project_code: Optional[str] = None
    name: str
    status: str


class UserProjectsResponse(BaseModel):
    """Returned by GET /user/users/{id}/projects/list."""

    user_id: str
    user_login: str
    projects: List[ProjectSummary] = Field(default_factory=list)


class VendorProjectsResponse(BaseModel):
    """Returned by GET /user/vendors/{vid}/projects/list."""

    vendor_id: str
    vendor_name: str
    projects: List[ProjectSummary] = Field(default_factory=list)
