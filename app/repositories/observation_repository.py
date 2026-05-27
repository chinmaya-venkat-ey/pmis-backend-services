"""ObservationRepository — DB access for metric_observations and sla_observation_band_counts."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.metric_observation import MetricObservation
from app.models.sla_observation_band_count import SlaObservationBandCount


class ObservationRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- observations

    def get_by_id(self, observation_id: str) -> Optional[MetricObservation]:
        return self.db.execute(
            select(MetricObservation).where(MetricObservation.id == observation_id)
        ).scalar_one_or_none()

    def list_for_sla(
        self,
        sla_id: str,
        *,
        status: Optional[str] = None,
        metric_key: Optional[str] = None,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        offset: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[MetricObservation], int]:
        stmt = select(MetricObservation).where(MetricObservation.sla_id == sla_id)
        count_stmt = (
            select(func.count())
            .select_from(MetricObservation)
            .where(MetricObservation.sla_id == sla_id)
        )

        if status:
            stmt = stmt.where(MetricObservation.status == status)
            count_stmt = count_stmt.where(MetricObservation.status == status)
        if metric_key:
            stmt = stmt.where(MetricObservation.metric_key == metric_key)
            count_stmt = count_stmt.where(MetricObservation.metric_key == metric_key)
        if period_start:
            stmt = stmt.where(MetricObservation.period_start >= period_start)
            count_stmt = count_stmt.where(MetricObservation.period_start >= period_start)
        if period_end:
            stmt = stmt.where(MetricObservation.period_end <= period_end)
            count_stmt = count_stmt.where(MetricObservation.period_end <= period_end)

        total = self.db.execute(count_stmt).scalar_one()
        rows = (
            self.db.execute(
                stmt.order_by(
                    MetricObservation.period_start.desc(),
                    MetricObservation.metric_key,
                )
                .offset((offset - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        return list(rows), total

    def create(self, obs: MetricObservation) -> MetricObservation:
        self.db.add(obs)
        self.db.flush()
        self.db.refresh(obs)
        return obs

    def update(self, obs: MetricObservation, **fields) -> MetricObservation:
        for key, value in fields.items():
            setattr(obs, key, value)
        obs.updated_at = datetime.utcnow()
        self.db.flush()
        self.db.refresh(obs)
        return obs

    # ---------------------------------------------------------------- band counts

    def get_band_counts(self, observation_id: str) -> List[SlaObservationBandCount]:
        return list(
            self.db.execute(
                select(SlaObservationBandCount)
                .where(SlaObservationBandCount.observation_id == observation_id)
                .order_by(SlaObservationBandCount.band_label)
            )
            .scalars()
            .all()
        )

    def replace_band_counts(
        self, observation_id: str, new_counts: List[SlaObservationBandCount]
    ) -> List[SlaObservationBandCount]:
        self.db.execute(
            delete(SlaObservationBandCount).where(
                SlaObservationBandCount.observation_id == observation_id
            )
        )
        for bc in new_counts:
            self.db.add(bc)
        self.db.flush()
        return new_counts
