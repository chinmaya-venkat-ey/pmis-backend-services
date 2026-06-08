"""TeamController — thin orchestration layer over TeamService."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.team import (
    ActivityAssignmentsRead,
    ActivityAssignmentsWrite,
    AssociatedUsersFilter,
    AssociatedUsersResponse,
    OwnershipRead,
    OwnershipWrite,
    TeamPageRequest,
    TeamPageResponse,
    TeamReadResponse,
    TeamWriteRequest,
    TeamWriteResponse,
)
from app.services.team_service import TeamService


class TeamController:
    def __init__(self, db: Session):
        self.service = TeamService(db)

    def get_team(self, project_id: str, *, authorization: str = "") -> TeamReadResponse:
        return self.service.get_team(project_id, authorization=authorization)

    # Bug #226: one delegator per Manage-Team candidate dropdown.
    def candidates_project_owners(self, project_id: str, *, authorization: str = ""):
        return self.service.candidates_project_owners(project_id, authorization=authorization)

    def candidates_project_owner_approvers(self, project_id: str, *, authorization: str = ""):
        return self.service.candidates_project_owner_approvers(project_id, authorization=authorization)

    def candidates_activity_members(self, project_id: str, *, division_code, authorization: str = ""):
        return self.service.candidates_activity_members(
            project_id, division_code=division_code, authorization=authorization,
        )

    def candidates_activity_approvers(self, project_id: str, *, division_code, authorization: str = ""):
        return self.service.candidates_activity_approvers(
            project_id, division_code=division_code, authorization=authorization,
        )

    def save_team(
        self,
        project_id: str,
        payload: TeamWriteRequest,
        caller_id: Optional[str],
    ) -> TeamWriteResponse:
        return self.service.save_team(project_id, payload, caller_id)

    def get_ownership(self, project_id: str) -> OwnershipRead:
        return self.service.get_ownership(project_id)

    def save_ownership(
        self,
        project_id: str,
        payload: OwnershipWrite,
        caller_id: Optional[str],
    ) -> OwnershipRead:
        return self.service.save_ownership(project_id, payload, caller_id)

    def get_activity_assignments(self, activity_id: str) -> ActivityAssignmentsRead:
        return self.service.get_activity_assignments(activity_id)

    def save_activity_assignments(
        self,
        activity_id: str,
        payload: ActivityAssignmentsWrite,
        caller_id: Optional[str],
    ) -> ActivityAssignmentsRead:
        return self.service.save_activity_assignments(activity_id, payload, caller_id)

    def get_associated_users(
        self,
        payload: AssociatedUsersFilter,
    ) -> AssociatedUsersResponse:
        return self.service.get_associated_users(payload)

    def get_team_page(self, project_id: str, *, authorization: str = "") -> TeamPageResponse:
        return self.service.get_team_page(project_id, authorization=authorization)

    def save_team_page(
        self,
        project_id: str,
        payload: TeamPageRequest,
        caller_id: Optional[str],
        authorization: str,
    ) -> TeamPageResponse:
        return self.service.save_team_page(project_id, payload, caller_id, authorization)
