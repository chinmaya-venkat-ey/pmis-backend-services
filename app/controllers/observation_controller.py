"""ObservationController — orchestrates ObservationService, shapes wire responses."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.schemas.observation import (
    BandCountResponse,
    BandCountSubmitRequest,
    ObservationCreateRequest,
    ObservationDetailResponse,
    ObservationExcludeRequest,
    ObservationResponse,
    ObservationUpdateRequest,
)
from app.services.observation_service import ObservationService


class ObservationController:
    def __init__(self, db: Session):
        self.service = ObservationService(db)

    # ---------------------------------------------------------------- reads

    def get(
        self, project_id: str, sla_id: str, observation_id: str
    ) -> ObservationDetailResponse:
        obs = self.service.get_by_id(project_id, sla_id, observation_id)
        band_counts = self.service.get_band_counts(project_id, sla_id, observation_id)
        return self._to_detail(obs, band_counts)

    def list_(
        self,
        project_id: str,
        sla_id: str,
        *,
        status: Optional[str] = None,
        metric_key: Optional[str] = None,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        offset: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ObservationResponse], int]:
        rows, total = self.service.list_for_sla(
            project_id,
            sla_id,
            status=status,
            metric_key=metric_key,
            period_start=period_start,
            period_end=period_end,
            offset=offset,
            page_size=page_size,
        )
        return [ObservationResponse.model_validate(r) for r in rows], total

    # ---------------------------------------------------------------- mutations

    def create(
        self,
        project_id: str,
        sla_id: str,
        payload: ObservationCreateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> ObservationDetailResponse:
        obs = self.service.create(
            project_id, sla_id, payload, caller_user_id=caller_user_id
        )
        band_counts = self.service.get_band_counts(project_id, sla_id, obs.id)
        return self._to_detail(obs, band_counts)

    def update(
        self,
        project_id: str,
        sla_id: str,
        observation_id: str,
        payload: ObservationUpdateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> ObservationDetailResponse:
        obs = self.service.update(
            project_id, sla_id, observation_id, payload, caller_user_id=caller_user_id
        )
        band_counts = self.service.get_band_counts(project_id, sla_id, observation_id)
        return self._to_detail(obs, band_counts)

    def approve(
        self,
        project_id: str,
        sla_id: str,
        observation_id: str,
        *,
        caller_user_id: Optional[str],
    ) -> ObservationResponse:
        obs = self.service.approve(
            project_id, sla_id, observation_id, caller_user_id=caller_user_id
        )
        return ObservationResponse.model_validate(obs)

    def reject(
        self,
        project_id: str,
        sla_id: str,
        observation_id: str,
        *,
        caller_user_id: Optional[str],
    ) -> ObservationResponse:
        obs = self.service.reject(
            project_id, sla_id, observation_id, caller_user_id=caller_user_id
        )
        return ObservationResponse.model_validate(obs)

    def exclude(
        self,
        project_id: str,
        sla_id: str,
        observation_id: str,
        payload: ObservationExcludeRequest,
    ) -> ObservationResponse:
        obs = self.service.exclude(project_id, sla_id, observation_id, payload)
        return ObservationResponse.model_validate(obs)

    def submit_band_counts(
        self,
        project_id: str,
        sla_id: str,
        observation_id: str,
        payload: BandCountSubmitRequest,
    ) -> List[BandCountResponse]:
        band_counts = self.service.submit_band_counts(
            project_id, sla_id, observation_id, payload
        )
        return [BandCountResponse.model_validate(bc) for bc in band_counts]

    # ---------------------------------------------------------------- response shaping

    @staticmethod
    def _to_detail(obs, band_counts) -> ObservationDetailResponse:
        return ObservationDetailResponse(
            **ObservationResponse.model_validate(obs).model_dump(),
            band_counts=[BandCountResponse.model_validate(bc) for bc in band_counts],
        )
