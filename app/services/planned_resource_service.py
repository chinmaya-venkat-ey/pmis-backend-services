"""PlannedResourceService — planned-resource rows on a resource-type phase.

Each row plans a headcount of a designation over a deployment window; its cost =
``quantity × monthly_rate × duration_months``:
  - ``monthly_rate`` is snapshotted from the (per-org) designation master.
  - ``duration_months`` = the deployment window as fractional months (days /
    30.44; see ``app.utilities.resource_duration``).

Multiple rows may share a designation (e.g. several consultants for different
durations) — they all accumulate into the cost item SUM. After every write the
owning ``resource_cost`` cost item's ``cost`` is set to the SUM of its live
planned-resource costs, so the existing payment / carry-forward math consumes the
planned total unchanged. Publish-lock is enforced (admin bypass), same as the rest
of the finance module.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.errors import ProjectNotFoundError, ValidationError
from app.models.planned_resource import PlannedResource
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.repositories.planned_resource_repository import PlannedResourceRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.planned_resource import (
    PlannedResourceCreateRequest,
    PlannedResourceUpdateRequest,
)
from app.utilities import resource_duration
from app.utilities.catalogs import designation_row
from app.utilities.payment_lock import assert_payment_writable

_RESOURCE_COST = "resource_cost"


def _dec(v) -> Decimal:
    if v is None:
        return Decimal("0")
    return v if isinstance(v, Decimal) else Decimal(str(v))


class PlannedResourceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PlannedResourceRepository(db)
        self.cost_items = ProjectCostItemRepository(db)
        self.projects = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ------------------------------------------------------------------ read

    def get_by_id(self, row_id: str) -> PlannedResource:
        row = self.repo.get_by_id(row_id)
        if row is None:
            raise ValidationError("The planned resource could not be found.")
        return row

    def list_for_project(self, project_id: str):
        self._require_project(project_id)
        return self.repo.list_for_project(project_id)

    def list_for_cost_item(self, cost_item_id: str):
        return self.repo.list_for_cost_item(cost_item_id)

    # ----------------------------------------------------------------- write

    def create(
        self, project_id: str, payload: PlannedResourceCreateRequest, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PlannedResource:
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        cost_item = self._require_resource_cost_item(project_id, payload.cost_item_id)
        rate, vendor_id = self._designation_rate(payload.designation_id)
        months, cost = self._compute(
            payload.deploy_start, payload.deploy_end, payload.quantity, rate,
        )

        row = self.repo.create(
            project_id=project_id,
            cost_item_id=cost_item.id,
            designation_id=payload.designation_id,
            vendor_id=vendor_id,
            quantity=payload.quantity,
            deploy_start=payload.deploy_start,
            deploy_end=payload.deploy_end,
            monthly_rate_snapshot=rate,
            duration_months=months,
            computed_cost=cost,
            position=self.repo.next_position_for_project(project_id),
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        self._repopulate_cost_item(cost_item.id)
        self.audit.write(
            project_id=project_id, target_kind="planned_resource", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"cost": {"before": None, "after": str(cost)}},
        )
        self.db.commit()
        return row

    def update(
        self, row_id: str, payload: PlannedResourceUpdateRequest, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PlannedResource:
        row = self.get_by_id(row_id)
        project = self._require_project(row.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        updates = payload.model_dump(exclude_unset=True)
        designation_id = updates.get("designation_id", row.designation_id)
        quantity = updates.get("quantity", row.quantity)
        deploy_start = updates.get("deploy_start", row.deploy_start)
        deploy_end = updates.get("deploy_end", row.deploy_end)

        rate, vendor_id = self._designation_rate(designation_id)
        months, cost = self._compute(deploy_start, deploy_end, quantity, rate)

        self.repo.update(
            row,
            designation_id=designation_id,
            vendor_id=vendor_id,
            quantity=quantity,
            deploy_start=deploy_start,
            deploy_end=deploy_end,
            monthly_rate_snapshot=rate,
            duration_months=months,
            computed_cost=cost,
            updated_by=caller_user_id,
        )
        self._repopulate_cost_item(row.cost_item_id)
        self.audit.write(
            project_id=row.project_id, target_kind="planned_resource", target_id=row.id,
            action="update", actor_user_id=caller_user_id,
            changes={"cost": {"after": str(cost)}},
        )
        self.db.commit()
        return row

    def delete(
        self, row_id: str, *, caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> None:
        row = self.get_by_id(row_id)
        project = self._require_project(row.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        cost_item_id = row.cost_item_id
        self.repo.soft_delete(row)
        self._repopulate_cost_item(cost_item_id)
        self.audit.write(
            project_id=row.project_id, target_kind="planned_resource", target_id=row.id,
            action="delete", actor_user_id=caller_user_id, changes={},
        )
        self.db.commit()

    # --------------------------------------------------------------- helpers

    def _compute(self, deploy_start, deploy_end, quantity, rate):
        """(duration_months, computed_cost) for a row:
        cost = quantity × monthly_rate × months."""
        months = resource_duration.duration_months(deploy_start, deploy_end)
        cost = (_dec(quantity) * _dec(rate) * months).quantize(Decimal("0.01"))
        return months, cost

    def _repopulate_cost_item(self, cost_item_id: str) -> None:
        """Set the resource_cost row's ``cost`` to the SUM of its live planned
        resources — the derived planned resource cost for the phase."""
        total = self.repo.sum_cost_for_cost_item(cost_item_id)
        cost_item = self.cost_items.get_by_id(cost_item_id)
        if cost_item is not None:
            self.cost_items.update(cost_item, cost=total)

    def _designation_rate(self, designation_id: str):
        d = designation_row(self.db, designation_id)
        if d is None:
            raise ValidationError(
                "The selected designation was not found (or is inactive)."
            )
        return (_dec(d.monthly_rate), d.vendor_id)

    def _require_resource_cost_item(self, project_id: str, cost_item_id: str):
        cost_item = self.cost_items.get_by_id(cost_item_id)
        if cost_item is None or cost_item.project_id != project_id:
            raise ValidationError("The cost item could not be found for this project.")
        if cost_item.cost_type_code != _RESOURCE_COST:
            raise ValidationError(
                "Planned resources can only be added to a resource-cost row."
            )
        return cost_item

    def _require_project(self, project_id: str):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        return project
