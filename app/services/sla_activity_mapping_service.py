"""SlaActivityMappingService — CRUD for SLA-Activity mappings."""
from __future__ import annotations

from typing import List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.formula_library import FormulaLibrary
from app.models.sla_activity_mapping import SlaActivityMapping
from app.repositories.sla_activity_mapping_repository import (
    SlaActivityMappingRepository,
)
from app.repositories.sla_repository import SlaRepository
from app.schemas.sla_activity_mapping import (
    SlaActivityMappingCreateRequest,
    SlaActivityMappingResponse,
    SlaActivityMappingUpdateRequest,
)


class SlaActivityMappingService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SlaActivityMappingRepository(db)
        self.sla_repo = SlaRepository(db)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _to_response(
        mapping: SlaActivityMapping,
        sla_ref: str,
        sla_title: str,
        contract_type: Optional[str],
        formula_type: Optional[str],
        category: Optional[str] = None,
    ) -> SlaActivityMappingResponse:
        return SlaActivityMappingResponse(
            id=mapping.id,
            activity_id=mapping.activity_id,
            sla_id=mapping.sla_id,
            sla_ref=sla_ref,
            sla_title=sla_title,
            contract_type=contract_type,
            formula_type=formula_type,
            category=category,
            overrides=mapping.overrides or {},
            status=mapping.status,
            effective_from=mapping.effective_from,
            effective_until=mapping.effective_until,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at,
        )

    # ---------------------------------------------------------------- create

    def create(
        self,
        payload: SlaActivityMappingCreateRequest,
        created_by: Optional[str] = None,
    ) -> SlaActivityMappingResponse:
        sla = self.sla_repo.get_by_id(payload.sla_id)
        if sla is None:
            raise NotFoundError(f"SLA '{payload.sla_id}' not found", code="sla_not_found")
        if sla.status == "DELETED":
            raise ConflictError(
                f"SLA '{sla.sla_ref}' is deleted and cannot be mapped",
                code="sla_deleted",
            )

        if payload.effective_until and payload.effective_until < payload.effective_from:
            raise ValidationError(
                "effective_until cannot be before effective_from",
                code="invalid_effective_range",
            )

        clash = self.repo.find_overlap(
            payload.activity_id, payload.sla_id, payload.effective_from
        )
        if clash is not None:
            raise ConflictError(
                f"SLA '{sla.sla_ref}' already mapped to activity "
                f"'{payload.activity_id}' with effective_from '{payload.effective_from}'",
                code="duplicate_mapping",
            )

        # Phase F1 — RFP §5.28.2.a phase-gate. Raises ValidationError(422)
        # when the SLA's phase classifier disagrees with the activity's
        # deliverable's configured phase. Fails-open (logs, allows) on
        # missing config / un-extractable deliverable code — see the
        # PhaseGateService docstring for the failure-open cases.
        from app.services.phase_gate_service import PhaseGateService
        PhaseGateService(self.db).assert_phase_matches(
            contract_type=sla.contract_type,
            sla_phase=getattr(sla, "phase", None),
            sla_ref=sla.sla_ref,
            activity_id=payload.activity_id,
        )

        row = SlaActivityMapping(
            id=str(uuid4()),
            activity_id=payload.activity_id,
            sla_id=payload.sla_id,
            overrides=payload.overrides or {},
            status="ACTIVE",
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
            created_by=created_by,
        )
        row = self.repo.create(row)

        formula_obj = self.db.get(FormulaLibrary, sla.formula_id) if sla.formula_id else None
        formula_type = formula_obj.formula_type if formula_obj else None
        return self._to_response(
            row, sla.sla_ref, sla.title, sla.contract_type, formula_type,
            category=sla.category,
        )

    # ---------------------------------------------------------------- update / delete

    def update(
        self, mapping_id: str, payload: SlaActivityMappingUpdateRequest
    ) -> SlaActivityMappingResponse:
        loaded = self.repo.load_with_sla(mapping_id)
        if loaded is None:
            raise NotFoundError(f"Mapping '{mapping_id}' not found", code="mapping_not_found")
        mapping, sla, formula_type = loaded

        updates = payload.model_dump(exclude_unset=True)
        if "overrides" in updates and updates["overrides"] is not None:
            merged = dict(mapping.overrides or {})
            merged.update(updates["overrides"])
            updates["overrides"] = merged

        if "effective_until" in updates and updates["effective_until"] is not None:
            if updates["effective_until"] < mapping.effective_from:
                raise ValidationError(
                    "effective_until cannot be before effective_from",
                    code="invalid_effective_range",
                )

        was_active = mapping.status != "RETIRED"
        if updates:
            mapping = self.repo.update(mapping, **updates)

        # When a PATCH retires the mapping, wipe its evaluation footprint so the
        # SLA stops surfacing in compliance views and stops feeding settlement.
        if was_active and mapping.status == "RETIRED":
            self._purge_evaluation_footprint(mapping.id)

        return self._to_response(
            mapping, sla.sla_ref, sla.title, sla.contract_type, formula_type,
            category=sla.category,
        )

    def unmap(self, mapping_id: str) -> SlaActivityMappingResponse:
        loaded = self.repo.load_with_sla(mapping_id)
        if loaded is None:
            raise NotFoundError(f"Mapping '{mapping_id}' not found", code="mapping_not_found")
        mapping, sla, formula_type = loaded
        if mapping.status == "RETIRED":
            raise ConflictError("Mapping is already retired", code="already_retired")
        mapping = self.repo.update(mapping, status="RETIRED")
        # Retiring must remove the mapping completely: delete the evaluation
        # results and quarterly-aggregate rows it produced while ACTIVE, else a
        # wrongly-mapped SLA keeps showing evaluations and counting toward LD.
        self._purge_evaluation_footprint(mapping.id)
        return self._to_response(
            mapping, sla.sla_ref, sla.title, sla.contract_type, formula_type,
            category=sla.category,
        )

    def _purge_evaluation_footprint(self, mapping_id: str) -> None:
        """Delete all evaluation results + quarterly aggregates for a mapping.

        Called when a mapping is retired so its prior evaluations no longer
        appear in compliance/settlement reads. The SLA definition, the mapping
        row (now RETIRED), and recorded observations are left intact."""
        from sqlalchemy import delete
        from app.models.sla_evaluation_result import SlaEvaluationResult
        from app.models.sla_quarterly_aggregate import SlaQuarterlyAggregate

        self.db.execute(
            delete(SlaEvaluationResult).where(
                SlaEvaluationResult.mapping_id == mapping_id
            )
        )
        self.db.execute(
            delete(SlaQuarterlyAggregate).where(
                SlaQuarterlyAggregate.mapping_id == mapping_id
            )
        )
        self.db.commit()

    # ---------------------------------------------------------------- read

    def list_for_activity(
        self, activity_id: str, *, active_only: bool = True
    ) -> List[SlaActivityMappingResponse]:
        rows = self.repo.list_for_activity(activity_id, active_only=active_only)
        return [
            self._to_response(m, sla.sla_ref, sla.title, sla.contract_type, ft,
                              category=sla.category)
            for (m, sla, ft) in rows
        ]

    def list_for_sla(
        self, sla_id: str, *, active_only: bool = True
    ) -> List[SlaActivityMappingResponse]:
        """Used by the SLA detail view to show 'Mapped Activities'.

        ``active_only`` (default True) hides retired mappings so a retired
        mapping drops off the list, matching ``list_for_activity``.
        """
        rows = self.repo.list_by_sla(sla_id, active_only=active_only)
        return [
            self._to_response(m, sla.sla_ref, sla.title, sla.contract_type, ft,
                              category=sla.category)
            for (m, sla, ft) in rows
        ]
