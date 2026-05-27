"""ProjectLdConfigService — business logic for project LD financial config."""
from __future__ import annotations

from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ProjectLdConfigNotFoundError
from app.models.project_ld_config import ProjectLdConfig
from app.repositories.project_ld_config_repository import ProjectLdConfigRepository
from app.schemas.project_ld_config import (
    ProjectLdConfigCreateRequest,
    ProjectLdConfigUpdateRequest,
)


class ProjectLdConfigService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProjectLdConfigRepository(db)

    def get_by_project_id(self, project_id: str) -> ProjectLdConfig:
        row = self.repo.get_by_project_id(project_id)
        if row is None:
            raise ProjectLdConfigNotFoundError(
                f"No LD config found for project '{project_id}'"
            )
        return row

    def create(
        self,
        project_id: str,
        payload: ProjectLdConfigCreateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> ProjectLdConfig:
        if self.repo.get_by_project_id(project_id) is not None:
            raise ConflictError(
                f"LD config already exists for project '{project_id}'",
                code="duplicate_project_ld_config",
            )
        if self.repo.get_by_contract_ref(payload.contract_ref) is not None:
            raise ConflictError(
                f"contract_ref '{payload.contract_ref}' already in use",
                code="duplicate_contract_ref",
            )

        sc = payload.scoring_config
        config = ProjectLdConfig(
            id=str(uuid4()),
            project_id=project_id,
            contract_ref=payload.contract_ref,
            total_value=payload.total_value,
            currency=payload.currency,
            quarterly_ld_cap_percent=payload.quarterly_ld_cap_percent,
            ld_status="ACTIVE",
            severity_points_map=sc.severity_points_map if sc else None,
            points_ld_map=sc.points_ld_map if sc else None,
            scoring_applies_to=sc.applies_to if sc else None,
            metadata_=payload.metadata,
            created_by=caller_user_id,
        )
        return self.repo.create(config)

    def update(
        self,
        project_id: str,
        payload: ProjectLdConfigUpdateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> ProjectLdConfig:
        config = self.get_by_project_id(project_id)
        updates = payload.model_dump(exclude_unset=True)

        if "metadata" in updates:
            updates["metadata_"] = updates.pop("metadata")

        sc_payload = updates.pop("scoring_config", None)
        if updates:
            self.repo.update(config, **updates)

        if sc_payload:
            self.repo.update(
                config,
                severity_points_map=sc_payload["severity_points_map"],
                points_ld_map=sc_payload["points_ld_map"],
                scoring_applies_to=sc_payload.get("applies_to", ["point_accumulation", "wac"]),
            )
        return config
