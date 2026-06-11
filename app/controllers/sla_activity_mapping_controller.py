"""Controllers for SLA-Activity mapping CRUD + evaluation."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.clients import ProjectManagementClient
from app.schemas.sla_activity_mapping import (
    SlaActivityMappingCreateRequest,
    SlaActivityMappingResponse,
    SlaActivityMappingUpdateRequest,
)
from app.schemas.sla_evaluation import (
    ActivityEvaluationRequest,
    ActivityEvaluationResponse,
    BulkEvaluationRequest,
    EvalFormSchema,
    MappingEvaluationRequest,
    MappingEvaluationResponse,
    SimpleEvaluationRequest,
)
from app.services.sla_activity_mapping_service import SlaActivityMappingService
from app.services.sla_evaluator import SlaEvaluatorService


class SlaActivityMappingController:
    def __init__(
        self,
        db: Session,
        project_mgmt_client: Optional[ProjectManagementClient] = None,
    ):
        self.service = SlaActivityMappingService(db)
        # project_mgmt_client is optional so unit tests can construct the
        # controller without DI. When None, the evaluator falls back to
        # default RFP scoring (no project_id resolution).
        self.evaluator = SlaEvaluatorService(
            db, project_mgmt_client=project_mgmt_client,
        )

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

    def list_for_sla(
        self, sla_id: str
    ) -> List[SlaActivityMappingResponse]:
        return self.service.list_for_sla(sla_id)

    # ------------------------------------------------------------------ evaluate

    def evaluate_mapping(
        self,
        mapping_id: str,
        payload: MappingEvaluationRequest,
        bearer_token: Optional[str] = None,
    ) -> MappingEvaluationResponse:
        return self.evaluator.evaluate_mapping(
            mapping_id, payload, bearer_token=bearer_token,
        )

    def evaluate_activity(
        self,
        activity_id: str,
        payload: ActivityEvaluationRequest,
        bearer_token: Optional[str] = None,
    ) -> ActivityEvaluationResponse:
        return self.evaluator.evaluate_activity(
            activity_id, payload, bearer_token=bearer_token,
        )

    # ----------------------------------------------- simple (sla_ref-keyed) evaluation

    def evaluate_by_sla_ref(
        self,
        activity_id: str,
        sla_ref: str,
        payload: SimpleEvaluationRequest,
        bearer_token: Optional[str] = None,
    ) -> MappingEvaluationResponse:
        return self.evaluator.evaluate_by_sla_ref(
            activity_id, sla_ref, payload, bearer_token=bearer_token,
        )

    def evaluate_activity_bulk(
        self,
        activity_id: str,
        payload: BulkEvaluationRequest,
        bearer_token: Optional[str] = None,
    ) -> ActivityEvaluationResponse:
        return self.evaluator.evaluate_activity_bulk(
            activity_id, payload, bearer_token=bearer_token,
        )

    def get_evaluation_form_schema(
        self,
        activity_id: str,
        sla_ref: str,
        bearer_token: Optional[str] = None,
    ) -> EvalFormSchema:
        return self.evaluator.get_evaluation_form_schema(
            activity_id, sla_ref, bearer_token=bearer_token,
        )
