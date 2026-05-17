"""Pydantic response models for ``/project/projects/{uuid}/tree``.

The tree endpoint returns a deeply-nested payload (milestones → activities
→ tasks → subtasks, with resource sidecars inlined). All datetime fields
are emitted as IST ISO 8601 strings (``+05:30``) — the service layer does
the formatting, so the schemas declare them as ``Optional[str]``.

Schemas live here for reference and `response_model` use, but the route
returns the raw payload dict (HAL envelope is NOT used by dashboard /
tree per the FE contract — see PMIS-OpenProject monolith's
``app/api/v3/tree/service.py``).
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TreeResourcePayload(BaseModel):
    """Inlined resource sidecar — same shape across A/T/S levels."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    resourceName: Optional[str] = None
    onboardDate: Optional[str] = None
    actualOnboardDate: Optional[str] = None
    offboardDate: Optional[str] = None
    actualOffboardDate: Optional[str] = None
    position: Optional[str] = None
    designation: Optional[str] = None
    jobRole: Optional[str] = None
    qualification: Optional[str] = None
    experienceYears: Optional[float] = None


class TreeSubtaskNode(BaseModel):
    """A subtask in the tree. ``subtasks`` is the nested-child list
    (Doc 24 variable-depth)."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    displayCode: Optional[str] = None
    taskId: str
    projectId: str
    parentSubtaskId: Optional[str] = None
    name: str
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignedTo: Optional[str] = None
    assignedToName: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    actualStartDate: Optional[str] = None
    actualEndDate: Optional[str] = None
    position: Optional[int] = None
    resourceMode: Optional[str] = None
    resourceCount: Optional[int] = None
    dependsOn: Annotated[List[str], Field(default_factory=list)]
    dependsOnDisplay: Annotated[List[str], Field(default_factory=list)]
    deletedAt: Optional[str] = None
    resource: Optional[TreeResourcePayload] = None
    scheduleStatus: str
    daysDelayed: Optional[int] = None
    # Self-referential; deferred to model_rebuild at the bottom.
    subtasks: Annotated[List["TreeSubtaskNode"], Field(default_factory=list)]


class TreeTaskNode(BaseModel):
    """A task in the tree. ``subtasks`` holds the top-level subtasks
    under this task; further nesting hangs off each subtask's own
    ``subtasks`` list."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    displayCode: Optional[str] = None
    activityId: str
    projectId: str
    name: str
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignedTo: Optional[str] = None
    assignedToName: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    actualStartDate: Optional[str] = None
    actualEndDate: Optional[str] = None
    position: Optional[int] = None
    resourceMode: Optional[str] = None
    resourceCount: Optional[int] = None
    dependsOn: Annotated[List[str], Field(default_factory=list)]
    dependsOnDisplay: Annotated[List[str], Field(default_factory=list)]
    deletedAt: Optional[str] = None
    resource: Optional[TreeResourcePayload] = None
    scheduleStatus: str
    daysDelayed: Optional[int] = None
    subtasks: Annotated[List[TreeSubtaskNode], Field(default_factory=list)]


class TreeActivityNode(BaseModel):
    """An activity in the tree."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    displayCode: Optional[str] = None
    milestoneId: str
    projectId: str
    name: str
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    ownerDivision: Optional[str] = None
    concernedDivision: Annotated[List[str], Field(default_factory=list)]
    vendorId: Optional[str] = None
    vendorName: Optional[str] = None
    priority: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    actualStartDate: Optional[str] = None
    actualEndDate: Optional[str] = None
    position: Optional[int] = None
    resourceMode: Optional[str] = None
    resourceCount: Optional[int] = None
    dependsOn: Annotated[List[str], Field(default_factory=list)]
    dependsOnDisplay: Annotated[List[str], Field(default_factory=list)]
    deletedAt: Optional[str] = None
    resource: Optional[TreeResourcePayload] = None
    scheduleStatus: str
    daysDelayed: Optional[int] = None
    tasks: Annotated[List[TreeTaskNode], Field(default_factory=list)]


class TreeMilestoneNode(BaseModel):
    """A milestone in the tree."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    displayCode: Optional[str] = None
    projectId: str
    name: str
    description: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    actualStartDate: Optional[str] = None
    actualEndDate: Optional[str] = None
    position: Optional[int] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    dependsOn: Annotated[List[str], Field(default_factory=list)]
    dependsOnDisplay: Annotated[List[str], Field(default_factory=list)]
    deletedAt: Optional[str] = None
    scheduleStatus: str
    daysDelayed: Optional[int] = None
    activities: Annotated[List[TreeActivityNode], Field(default_factory=list)]


class TreeProjectHeader(BaseModel):
    """The project header card at the root of the tree response."""

    model_config = ConfigDict(from_attributes=False)

    id: Optional[str] = None
    projectCode: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    category: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    isPublic: Optional[bool] = None


class TreeCounts(BaseModel):
    """Per-tree counts (observability + FE rendering hints)."""

    model_config = ConfigDict(from_attributes=False)

    milestones: int = 0
    activities: int = 0
    tasks: int = 0
    subtasks: int = 0
    activityResources: int = 0
    taskResources: int = 0
    subtaskResources: int = 0


class TreeResponse(BaseModel):
    """``GET /project/projects/{uuid}/tree`` — full M/A/T/S tree."""

    model_config = ConfigDict(from_attributes=False)

    type: str = Field(default="ProjectTree", alias="_type")
    links: Annotated[Dict[str, Any], Field(default_factory=dict, alias="_links")]
    project: TreeProjectHeader
    counts: TreeCounts
    milestones: Annotated[List[TreeMilestoneNode], Field(default_factory=list)]


# Self-referential subtask requires explicit rebuild.
TreeSubtaskNode.model_rebuild()
TreeTaskNode.model_rebuild()
TreeActivityNode.model_rebuild()
TreeMilestoneNode.model_rebuild()
TreeResponse.model_rebuild()
