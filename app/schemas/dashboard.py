"""Pydantic response models for ``/project/dashboard/*``.

Wire shape only — no input validation surface. Every endpoint is a GET
with at most a handful of query params validated inline at the route.

All datetime fields are emitted as IST ISO 8601 strings (``+05:30``).
The conversion happens in the service layer via ``iso_ist`` so these
schemas declare them as ``Optional[str]``.

Ported verbatim from PMIS-OpenProject monolith's
``app/api/v3/dashboard/schemas.py`` — keep camelCase wire names per the
existing FE contract.
"""
from __future__ import annotations

from typing import Annotated, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

class VendorChip(BaseModel):
    """Slim vendor representation used everywhere a project's
    organisation list is rendered."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    name: str
    active: bool


class BucketCounts(BaseModel):
    """Project bucket counts (three mutually-exclusive buckets).
    ``total`` is the sum of the three buckets — emitted explicitly so
    the FE doesn't have to recompute it.

    There is no ``active`` field at the project level. The Summary
    view's "Active Projects" KPI tile is computed by the FE as
    ``total - completed`` (i.e. ``ontrack + delayed``).

    ``pendingApprovalCount`` is a static placeholder until the approval
    workflow integration lands — see
    ``app/services/dashboard_service.py:_STATIC_PENDING_APPROVAL_COUNT``.
    """

    model_config = ConfigDict(from_attributes=False)

    total: int = 0
    ontrack: int = 0
    delayed: int = 0
    completed: int = 0
    pendingApprovalCount: int = 0


class DivisionCard(BaseModel):
    """One row in the Summary view's Division card grid."""

    model_config = ConfigDict(from_attributes=False)

    code: str
    label: str
    projectCount: int
    counts: BucketCounts


class OrganisationCard(BaseModel):
    """One row in the Organization view's vendor grid (and the Summary
    view's top-N cards)."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    name: str
    active: bool
    projectCount: int
    counts: BucketCounts


class DelayedTrackProject(BaseModel):
    """Summary view's Delayed Track row — one project per row, with
    aggregate delay info."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    projectCode: Optional[str] = None
    name: str
    organisations: Annotated[List[VendorChip], Field(default_factory=list)]
    division: Optional[str] = None
    divisionOther: Optional[str] = None
    delayedItemCount: int
    maxDelayDays: int


class ProjectCard(BaseModel):
    """A single project's representation across the dashboard. Used by:
    Summary view (when listing projects under a bucket), Project picker,
    Organization detail page, Project Listing page.
    """

    model_config = ConfigDict(from_attributes=False)

    id: str
    projectCode: Optional[str] = None
    name: str
    description: Optional[str] = None
    organisations: Annotated[List[VendorChip], Field(default_factory=list)]
    division: Optional[str] = None
    divisionOther: Optional[str] = None
    lifecycleStatus: str
    bucket: str
    progressPct: int
    plannedStart: Optional[str] = None
    plannedEnd: Optional[str] = None
    actualStart: Optional[str] = None
    actualEnd: Optional[str] = None
    milestonesTotal: int = 0
    milestonesCompleted: int = 0
    activitiesTotal: int = 0
    activitiesCompleted: int = 0
    delayedItemCount: int = 0
    maxDelayDays: int = 0


# ---------------------------------------------------------------------------
# Endpoint envelopes
# ---------------------------------------------------------------------------

class SummaryResponse(BaseModel):
    """``GET /project/dashboard/summary`` — feeds the Summary view's KPI
    strip, project pie, top org / division cards, and delayed track."""

    model_config = ConfigDict(from_attributes=False)

    asOf: str  # ISO IST date string of "today"
    delayMinDays: int
    counts: BucketCounts
    delayedTrack: Annotated[List[DelayedTrackProject], Field(default_factory=list)]
    topOrganisations: Annotated[List[OrganisationCard], Field(default_factory=list)]
    topDivisions: Annotated[List[DivisionCard], Field(default_factory=list)]


class ProjectListResponse(BaseModel):
    """``GET /project/dashboard/projects`` — paginated project cards with
    optional filters."""

    model_config = ConfigDict(from_attributes=False)

    asOf: str
    page: int
    pageSize: int
    total: int
    counts: BucketCounts
    projects: List[ProjectCard]


class ProjectKpis(BaseModel):
    """Five KPI tiles on the Project View screen."""

    model_config = ConfigDict(from_attributes=False)

    progressPct: int
    milestonesTotal: int
    milestonesCompleted: int
    milestonesDelayed: int
    milestonesOntrack: int
    activitiesTotal: int
    activitiesCompleted: int
    activitiesDelayed: int
    activitiesOntrack: int
    pendingApprovalCount: int  # static placeholder until approval-workflow integration
    delayedCount: int


class DelayedItemRow(BaseModel):
    """One row in the Project View's Delayed Track card."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    kind: str  # "milestone" | "activity"
    wbs: str
    name: str
    milestoneId: Optional[str] = None
    milestoneName: Optional[str] = None
    plannedStart: Optional[str] = None
    plannedEnd: Optional[str] = None
    actualStart: Optional[str] = None
    actualEnd: Optional[str] = None
    daysDelayed: int


class ProjectDetailResponse(BaseModel):
    """``GET /project/dashboard/projects/{id}`` — feeds the Project View
    screen (header + KPIs + project pie + delayed track)."""

    model_config = ConfigDict(from_attributes=False)

    asOf: str
    delayMinDays: int
    project: ProjectCard
    kpis: ProjectKpis
    pie: BucketCounts  # over M/A items only (active will be 0)
    delayedTrack: Annotated[List[DelayedItemRow], Field(default_factory=list)]


class ItemRow(BaseModel):
    """A milestone or activity row in the drill-down table.

    ``wbs`` is the display label the FE shows in the WBS column —
    ``M{n}`` for milestones and ``A{n}.{k}`` for activities (where
    ``n`` is the milestone position and ``k`` the activity position).
    """

    model_config = ConfigDict(from_attributes=False)

    id: str
    kind: str  # "milestone" | "activity"
    wbs: str
    name: str
    milestoneId: Optional[str] = None
    milestoneName: Optional[str] = None
    status: Optional[str] = None
    bucket: str
    plannedStart: Optional[str] = None
    plannedEnd: Optional[str] = None
    actualStart: Optional[str] = None
    actualEnd: Optional[str] = None
    daysDelayed: int = 0
    progressPct: int = 0  # for milestones: % of their activities completed


class ProjectItemsResponse(BaseModel):
    """``GET /project/dashboard/projects/{id}/items`` — drill-down for
    KPI clicks. Returns M/A rows under filters."""

    model_config = ConfigDict(from_attributes=False)

    asOf: str
    counts: Dict[str, int]  # {total, completed, delayed, ontrack}
    rows: List[ItemRow]


class OrganisationVendorPie(BaseModel):
    """Top-of-page pie on the Organization view: vendor catalog
    distribution by ``active`` flag (not project counts)."""

    model_config = ConfigDict(from_attributes=False)

    activeVendors: int
    inactiveVendors: int
    total: int


class OrganisationsResponse(BaseModel):
    """``GET /project/dashboard/organisations`` — full vendor grid for
    the Organization view top page."""

    model_config = ConfigDict(from_attributes=False)

    asOf: str
    pie: OrganisationVendorPie
    organisations: List[OrganisationCard]


class OrganisationDetailResponse(BaseModel):
    """``GET /project/dashboard/organisations/{vendorId}`` — vendor
    detail page (KPIs + project pie + project listing)."""

    model_config = ConfigDict(from_attributes=False)

    asOf: str
    organisation: OrganisationCard
    pie: BucketCounts
    projects: List[ProjectCard]
