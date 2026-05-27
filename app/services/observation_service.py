"""ObservationService — business logic for metric observations.

Create flow:
  1. Verify SLA exists and belongs to contract
  2. Guard: SLA must be ACTIVE (Gap 3)
  3. Guard: period within SLA effective dates (Gap 3)
  4. Guard: metric_key exists in sla_metrics; observed_unit matches (Gap 2)
  5. Insert metric_observations row (PENDING)
  6. If IntegrityError → DuplicateObservationError (unique constraint on sla+metric+period)
  7. If inline band_counts provided: validate formula=band_accumulation + band ownership, then insert

Approve/Reject/Update: only PENDING observations (Gap 4 principle).
Exclude: PENDING or APPROVED allowed, REJECTED blocked (Gap 6 reversal supported).
Band count submit: PENDING + band_accumulation formula + band belongs to SLA (Gaps 1,4,5).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    DuplicateObservationError,
    ObservationNotFoundError,
    SlaNotFoundError,
    ValidationError,
)
from app.models.formula_library import FormulaLibrary
from app.models.metric_observation import MetricObservation
from app.models.sla_condition_band import SlaConditionBand
from app.models.sla_metric import SlaMetric
from app.models.sla_observation_band_count import SlaObservationBandCount
from app.repositories.observation_repository import ObservationRepository
from app.repositories.sla_repository import SlaRepository
from app.schemas.observation import (
    BandCountRequest,
    BandCountSubmitRequest,
    ObservationCreateRequest,
    ObservationExcludeRequest,
    ObservationUpdateRequest,
)


class ObservationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ObservationRepository(db)
        self.sla_repo = SlaRepository(db)

    # ---------------------------------------------------------------- reads

    def get_by_id(
        self, contract_id: str, sla_id: str, observation_id: str
    ) -> MetricObservation:
        self._require_sla(contract_id, sla_id)
        obs = self.repo.get_by_id(observation_id)
        if obs is None or obs.sla_id != sla_id:
            raise ObservationNotFoundError(
                f"Observation '{observation_id}' not found on SLA '{sla_id}'"
            )
        return obs

    def list_for_sla(
        self,
        contract_id: str,
        sla_id: str,
        *,
        status: Optional[str] = None,
        metric_key: Optional[str] = None,
        period_start=None,
        period_end=None,
        offset: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[MetricObservation], int]:
        self._require_sla(contract_id, sla_id)
        return self.repo.list_for_sla(
            sla_id,
            status=status,
            metric_key=metric_key,
            period_start=period_start,
            period_end=period_end,
            offset=offset,
            page_size=page_size,
        )

    # ---------------------------------------------------------------- create

    def create(
        self,
        contract_id: str,
        sla_id: str,
        payload: ObservationCreateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> MetricObservation:
        sla = self._require_sla(contract_id, sla_id)

        # Gap 3: SLA must be ACTIVE
        if sla.status != "ACTIVE":
            raise ValidationError(
                f"Cannot submit observations for SLA with status '{sla.status}'"
            )

        # Gap 3: period must fall within SLA effective dates
        if payload.period_start < sla.effective_from:
            raise ValidationError(
                f"period_start {payload.period_start} is before SLA "
                f"effective_from {sla.effective_from}"
            )
        if sla.effective_until and payload.period_end > sla.effective_until:
            raise ValidationError(
                f"period_end {payload.period_end} is after SLA "
                f"effective_until {sla.effective_until}"
            )

        # Gap 2: metric_key must exist + observed_unit must match metric unit
        metric = self._require_metric(sla_id, payload.metric_key)
        if payload.observed_unit.upper() != metric.unit.upper():
            raise ValidationError(
                f"observed_unit '{payload.observed_unit}' does not match "
                f"SLA metric unit '{metric.unit}' for metric_key '{payload.metric_key}'"
            )

        obs = MetricObservation(
            id=str(uuid4()),
            sla_id=sla_id,
            metric_key=payload.metric_key,
            period_start=payload.period_start,
            period_end=payload.period_end,
            observed_value=payload.observed_value,
            observed_unit=payload.observed_unit,
            baseline_used=payload.baseline_used,
            excluded_from_sla=payload.excluded_from_sla,
            exclusion_reason=payload.exclusion_reason,
            additional_inputs=payload.additional_inputs,
            data_source=payload.data_source,
            submitted_by=caller_user_id,
            status="PENDING",
        )
        try:
            self.repo.create(obs)
        except IntegrityError:
            self.db.rollback()
            raise DuplicateObservationError(
                f"Observation for metric '{payload.metric_key}' period "
                f"{payload.period_start}–{payload.period_end} already exists on SLA '{sla_id}'"
            )

        # Inline band counts (optional convenience — Gap 1 validated inside)
        if payload.band_counts:
            self._validate_band_accumulation(sla_id)
            self._replace_band_counts(sla_id, obs.id, payload.band_counts)

        return obs

    # ---------------------------------------------------------------- update

    def update(
        self,
        contract_id: str,
        sla_id: str,
        observation_id: str,
        payload: ObservationUpdateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> MetricObservation:
        obs = self.get_by_id(contract_id, sla_id, observation_id)
        self._require_pending(obs)
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return obs
        # Gap 2: re-validate unit if observed_unit is being changed
        if "observed_unit" in updates:
            metric = self._require_metric(sla_id, obs.metric_key)
            if updates["observed_unit"].upper() != metric.unit.upper():
                raise ValidationError(
                    f"observed_unit '{updates['observed_unit']}' does not match "
                    f"SLA metric unit '{metric.unit}'"
                )
        return self.repo.update(obs, **updates)

    # ---------------------------------------------------------------- approve / reject

    def approve(
        self,
        contract_id: str,
        sla_id: str,
        observation_id: str,
        *,
        caller_user_id: Optional[str],
    ) -> MetricObservation:
        obs = self.get_by_id(contract_id, sla_id, observation_id)
        self._require_pending(obs)
        return self.repo.update(
            obs,
            status="APPROVED",
            approved_by=caller_user_id,
            approved_at=datetime.utcnow(),
        )

    def reject(
        self,
        contract_id: str,
        sla_id: str,
        observation_id: str,
        *,
        caller_user_id: Optional[str],
    ) -> MetricObservation:
        obs = self.get_by_id(contract_id, sla_id, observation_id)
        self._require_pending(obs)
        return self.repo.update(obs, status="REJECTED")

    # ---------------------------------------------------------------- exclude

    def exclude(
        self,
        contract_id: str,
        sla_id: str,
        observation_id: str,
        payload: ObservationExcludeRequest,
    ) -> MetricObservation:
        obs = self.get_by_id(contract_id, sla_id, observation_id)
        # Gap 6: REJECTED observations cannot be modified
        if obs.status == "REJECTED":
            raise ValidationError(
                "Cannot change exclusion on a REJECTED observation"
            )
        return self.repo.update(
            obs,
            excluded_from_sla=payload.excluded,
            exclusion_reason=payload.exclusion_reason if payload.excluded else None,
        )

    # ---------------------------------------------------------------- band counts

    def submit_band_counts(
        self,
        contract_id: str,
        sla_id: str,
        observation_id: str,
        payload: BandCountSubmitRequest,
    ) -> List[SlaObservationBandCount]:
        obs = self.get_by_id(contract_id, sla_id, observation_id)
        # Gap 4: only PENDING observations accept band count changes
        self._require_pending(obs)
        # Gap 1: formula must be band_accumulation
        self._validate_band_accumulation(sla_id)
        return self._replace_band_counts(sla_id, observation_id, payload.band_counts)

    def get_band_counts(
        self, contract_id: str, sla_id: str, observation_id: str
    ) -> List[SlaObservationBandCount]:
        self.get_by_id(contract_id, sla_id, observation_id)
        return self.repo.get_band_counts(observation_id)

    # ---------------------------------------------------------------- internals

    def _require_sla(self, contract_id: str, sla_id: str):
        sla = self.sla_repo.get_by_id(sla_id)
        if sla is None or sla.contract_id != contract_id:
            raise SlaNotFoundError(
                f"SLA '{sla_id}' not found on contract '{contract_id}'"
            )
        return sla

    def _require_pending(self, obs: MetricObservation) -> None:
        if obs.status != "PENDING":
            raise ValidationError(
                f"Observation is '{obs.status}' — only PENDING observations can be modified"
            )

    def _require_metric(self, sla_id: str, metric_key: str) -> SlaMetric:
        metric = self.db.execute(
            select(SlaMetric).where(
                SlaMetric.sla_id == sla_id,
                SlaMetric.metric_key == metric_key,
            )
        ).scalar_one_or_none()
        if metric is None:
            raise ValidationError(
                f"metric_key '{metric_key}' does not exist on SLA '{sla_id}'"
            )
        return metric

    def _validate_band_accumulation(self, sla_id: str) -> None:
        """Gap 1: band counts only valid for band_accumulation formula."""
        sla = self.sla_repo.get_by_id(sla_id)
        formula = self.db.execute(
            select(FormulaLibrary).where(FormulaLibrary.id == sla.formula_id)
        ).scalar_one_or_none()
        if formula is None or formula.formula_type != "band_accumulation":
            raise ValidationError(
                "Band counts can only be submitted for band_accumulation SLAs (BSP/MSIP)"
            )

    def _replace_band_counts(
        self,
        sla_id: str,
        observation_id: str,
        band_counts: List[BandCountRequest],
    ) -> List[SlaObservationBandCount]:
        """Gap 5: validate each band_id belongs to this SLA, then replace."""
        new_rows = []
        for bc in band_counts:
            band = self.db.execute(
                select(SlaConditionBand).where(SlaConditionBand.id == bc.band_id)
            ).scalar_one_or_none()
            if band is None or band.sla_id != sla_id:
                raise ValidationError(
                    f"band_id '{bc.band_id}' does not belong to SLA '{sla_id}'"
                )
            new_rows.append(
                SlaObservationBandCount(
                    id=str(uuid4()),
                    observation_id=observation_id,
                    band_id=bc.band_id,
                    band_label=bc.band_label,
                    unit_count=bc.unit_count,
                )
            )
        return self.repo.replace_band_counts(observation_id, new_rows)
