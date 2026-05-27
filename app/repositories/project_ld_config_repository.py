"""ProjectLdConfigRepository — DB access for project_ld_config."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_ld_config import ProjectLdConfig


class ProjectLdConfigRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_project_id(self, project_id: str) -> Optional[ProjectLdConfig]:
        return self.db.execute(
            select(ProjectLdConfig).where(ProjectLdConfig.project_id == project_id)
        ).scalar_one_or_none()

    def get_by_contract_ref(self, contract_ref: str) -> Optional[ProjectLdConfig]:
        return self.db.execute(
            select(ProjectLdConfig).where(ProjectLdConfig.contract_ref == contract_ref)
        ).scalar_one_or_none()

    def create(self, config: ProjectLdConfig) -> ProjectLdConfig:
        self.db.add(config)
        self.db.flush()
        self.db.refresh(config)
        return config

    def update(self, config: ProjectLdConfig, **fields) -> ProjectLdConfig:
        for key, value in fields.items():
            setattr(config, key, value)
        config.updated_at = datetime.utcnow()
        self.db.flush()
        self.db.refresh(config)
        return config
