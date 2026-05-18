"""CriticalPathController — thin facade over CriticalPathService."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.schemas.critical_path import (
    CpaActivityOverride,
    CpaAnalysisResponse,
    CpaDependencyResponse,
)
from app.services.critical_path_service import CriticalPathService


def _bare(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload["_bare"] = True
    return payload


class CriticalPathController:
    def __init__(self, db: Session):
        self.db = db
        self.service = CriticalPathService(db)

    def dependencies(self, project_id: str) -> Dict[str, Any]:
        result = self.service.get_dependencies(project_id)
        return _bare(result.model_dump())

    def analysis(
        self,
        project_id: str,
        overrides: Optional[List[CpaActivityOverride]] = None,
    ) -> Dict[str, Any]:
        result = self.service.get_analysis(project_id, overrides=overrides)
        return _bare(result.model_dump())
