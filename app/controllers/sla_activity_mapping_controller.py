"""Controllers for SLA-Activity mapping CRUD + evaluation."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.schemas.sla_activity_mapping import (
    SlaActivityMappingCreateRequest,
    SlaActivityMappingResponse,
    SlaActivityMappingUpdateRequest,
)
from app.schemas.sla_evaluation import (
    ActivityEvaluationRequest,
    ActivityEvaluationResponse,
    MappingEvaluationRequest,
    MappingEvaluationResponse,
)
from app.services.sla_activity_mapping_service import SlaActivityMappingService
from app.services.sla_evaluator import SlaEvaluatorService


class SlaActivityMappingController:
    def __init__(self, db: Session):
        self.service = SlaActivityMappingService(db)
        self.evaluator = SlaEvaluatorService(db)

    # ------------------------------------------------------------------ CRUD

    def create(
        self,
        payload: SlaActivityMappingCreateRequest,
        created_by: Optional[str] = None,
    ) -> SlaActivityMappingResponse:
        return self.service.create(payload, created_by=created_by)

    def update(
        self, mapping_id: str, payload: SlaActivityMappingUpdateRequest
    ) -> SlaActivityMappingResponse:
        return self.service.update(mapping_id, payload)

    def unmap(self, mapping_id: str) -> SlaActivityMappingResponse:
        return self.service.unmap(mapping_id)

    def list_for_activity(
        self, activity_id: str, active_only: bool = True
    ) -> List[SlaActivityMappingResponse]:
        return self.service.list_for_activity(activity_id, active_only=active_only)

    # ------------------------------------------------------------------ evaluate

    def evaluate_mapping(
        self, mapping_id: str, payload: MappingEvaluationRequest
    ) -> MappingEvaluationResponse:
        return self.evaluator.evaluate_mapping(mapping_id, payload)

    def evaluate_activity(
        self, activity_id: str, payload: ActivityEvaluationRequest
    ) -> ActivityEvaluationResponse:
        return self.evaluator.evaluate_activity(activity_id, payload)
