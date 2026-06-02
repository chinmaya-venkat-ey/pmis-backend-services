"""Pydantic schemas for the Activity Approval Inbox APIs.

Endpoints:
  GET /api/v3/activities/approval-inbox            — list rows for caller's role
  GET /api/v3/activities/approval-inbox/{business_id} — detail for one item

Wire shape follows the project-mgmt convention: fields are snake_case in
Python, auto-camelCased on the wire by ``HalApiRoute._camelize``.

The detail response composes data from two sources:
  * PMIS (activity row + project + vendor + tracker)        — local DB
  * Java workflow service (state + transition history)       — HTTP
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._base import ResponseModel


# ── Tiny embedded blocks ───────────────────────────────────────────────────

class _InboxActivity(ResponseModel):
    id: str = Field(..., description="Activity UUID (== businessId)")
    display_code: Optional[str] = Field(
        default=None,
        description="A{m}.{a} short code derived from milestone+activity positions",
    )
    name: str


class _InboxProject(ResponseModel):
    id: str
    code: Optional[str] = None
    name: str


class _InboxActivityDetail(_InboxActivity):
    """Activity Details block on the review screen."""

    description: Optional[str] = None
    planned_start_date: Optional[datetime] = None
    planned_end_date: Optional[datetime] = None
    owner_division: Optional[str] = None
    owner_division_other: Optional[str] = None
    consent_divisions: List[str] = Field(default_factory=list)
    consent_division_other: Optional[str] = None


class _SubmissionEntry(ResponseModel):
    """One row of 'Organization Submission' — comes from Java's transition
    history. ``attachments`` is intentionally a list of opaque dicts for
    now (S3-backed attachments come later)."""

    who: Optional[str] = Field(default=None, description="userName from Java RequestInfo")
    when: Optional[datetime] = None
    text: Optional[str] = Field(default=None, description="The transition's ``comment``")
    attachments: List[dict] = Field(default_factory=list)


class _Submission(ResponseModel):
    comments: List[_SubmissionEntry] = Field(default_factory=list)


class _DivisionDecision(ResponseModel):
    """One row of 'Division Status'. In Model A (single-approval) Java
    surfaces one APPROVE/REJECT per concerned-division stage, but PMIS
    still shows one row per consent division on the screen — pending
    rows are inferred from the snapshot ``consent_divisions``."""

    division: str
    status: str = Field(..., description="pending | approved | rejected")
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    comment: Optional[str] = None


class _OwnerDecision(ResponseModel):
    status: str = Field(..., description="pending | approved | rejected")
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    comment: Optional[str] = None


class _MyView(ResponseModel):
    role: str = Field(..., description="concerned_division | activity_owner | admin")
    my_division: Optional[str] = None
    my_status: str = Field(..., description="pending | approved | rejected")
    can_approve: bool = False
    can_reject: bool = False


# ── Inbox row (list response item) ─────────────────────────────────────────

class InboxRow(ResponseModel):
    """One row in the inbox list (Activity, Project, Organization,
    Submitted, Status, Action)."""

    _hal_type = "ApprovalInboxItem"

    business_id: str = Field(..., description="Activity UUID — also the row id")
    process_instance_id: Optional[str] = None
    activity: _InboxActivity
    project: _InboxProject
    organization: Optional[str] = Field(
        default=None, description="Vendor name (the activity's organization)"
    )
    submitted_at: Optional[datetime] = None
    status: str = Field(..., description="pending | approved | rejected")


class InboxListResponse(ResponseModel):
    """Wraps a list of inbox rows + a ``total`` so the FE can render the
    ``(N)`` counter. The HAL collection envelope is still applied by
    ``HalApiRoute`` on top."""

    _hal_type = "Collection"

    total: int = 0
    items: List[InboxRow] = Field(default_factory=list)


# ── Inbox detail (review response) ─────────────────────────────────────────

class InboxDetailResponse(ResponseModel):
    _hal_type = "ApprovalInboxDetail"

    business_id: str
    process_instance_id: Optional[str] = None
    activity: _InboxActivityDetail
    project: _InboxProject
    organization: Optional[str] = None
    submitted_at: Optional[datetime] = None

    submission: _Submission = Field(default_factory=_Submission)
    status: str = Field(..., description="Overall FE-facing status")
    division_decisions: List[_DivisionDecision] = Field(default_factory=list)
    owner_decision: Optional[_OwnerDecision] = None
    my_view: _MyView


# ── Transition request / response ──────────────────────────────────────────

class TransitionRequest(BaseModel):
    """Body for POST /api/v3/approval-inbox/{business_id}/_transition."""

    model_config = ConfigDict(extra="ignore")

    action: str = Field(
        ..., description="SUBMIT | APPROVE | REJECT | UPDATE",
    )
    comment: Optional[str] = Field(
        default=None,
        description=(
            "Free-text. Required when action=REJECT (the rejection reason)."
        ),
    )


# Response is intentionally the same shape as the detail GET — the FE can
# overwrite the local detail state from the proxy response without an
# extra round-trip.


# ── Optional query-filter model (kept lightweight) ─────────────────────────

class InboxListFilter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Optional[str] = Field(
        default=None,
        description=(
            "Override caller's auto-detected role: concerned_division | "
            "activity_owner | admin. Default = derived from caller."
        ),
    )
    status: Optional[str] = Field(
        default=None,
        description="pending | approved | rejected | all (default: pending)",
    )
    search: Optional[str] = Field(
        default=None, description="Free-text — activity / project / organization"
    )
