"""PlannedResourceService — planned-resource rows on a resource-type phase.

Each row plans a headcount of a designation (``role``) over a deployment window,
priced from the client-supplied per-contract-year rate card (sourced from the
leave-management ``/api/designation-rates`` service). Cost is split BY CONTRACT
YEAR: for each year the window spans, ``quantity × rateCardByYear["Year-N"] ×
months-in-that-year`` (fractional months, days / 30.44), summed into
``computed_cost`` (per-year detail in ``cost_by_year``). Contract-year boundaries
are anchored on ``project.start_date`` via the existing ``cf_pool`` bucket helpers.

Multiple rows may share a role — they all accumulate into the cost item SUM. After
every write the owning ``resource_cost`` cost item's ``cost`` is set to the SUM of
its live planned-resource costs, so the existing payment / carry-forward math
consumes the planned total unchanged. Publish-lock is enforced (admin bypass).
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
from app.utilities import cf_pool, resource_duration
from app.utilities.payment_lock import assert_payment_writable

_RESOURCE_COST = "resource_cost"
_YEARLY = "yearly"


def _dec(v) -> Decimal:
    if v is None:
        return Decimal("0")
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _jsonable(d) -> dict:
    """Coerce a ``{year: amount}`` map to JSON-safe floats for JSONB storage
    (Decimal is not JSON-serialisable)."""
    return {k: float(_dec(v)) for k, v in (d or {}).items()}


def _rate_for_year(rate_card: dict, year_no: int) -> Decimal:
    """Rate for contract ``year_no`` (1-based) from the ``rateCardByYear`` map,
    clamping to the nearest available year when the window runs past the card."""
    if not rate_card:
        return Decimal("0")
    n = max(1, year_no)
    key = f"Year-{n}"
    if key in rate_card:
        return _dec(rate_card[key])
    years = [
        int(k.split("-", 1)[1])
        for k in rate_card
        if k.startswith("Year-") and k.split("-", 1)[1].isdigit()
    ]
    if not years:
        return Decimal("0")
    clamped = min(max(n, min(years)), max(years))
    return _dec(rate_card.get(f"Year-{clamped}"))


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
        rate_card = payload.rate_card_by_year or {}
        months, cost_by_year, cost = self._compute(
            payload.deploy_start, payload.deploy_end, payload.quantity, rate_card,
            project.start_date,
        )

        row = self.repo.create(
            project_id=project_id,
            cost_item_id=cost_item.id,
            role=payload.role,
            vendor_id=payload.organisation_id,
            quantity=payload.quantity,
            deploy_start=payload.deploy_start,
            deploy_end=payload.deploy_end,
            rate_card_snapshot=_jsonable(rate_card),
            cost_by_year=_jsonable(cost_by_year),
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
        role = updates.get("role", row.role)
        organisation_id = updates.get("organisation_id", row.vendor_id)
        quantity = updates.get("quantity", row.quantity)
        deploy_start = updates.get("deploy_start", row.deploy_start)
        deploy_end = updates.get("deploy_end", row.deploy_end)
        rate_card = updates.get("rate_card_by_year") or row.rate_card_snapshot or {}

        months, cost_by_year, cost = self._compute(
            deploy_start, deploy_end, quantity, rate_card, project.start_date,
        )

        self.repo.update(
            row,
            role=role,
            vendor_id=organisation_id,
            quantity=quantity,
            deploy_start=deploy_start,
            deploy_end=deploy_end,
            rate_card_snapshot=_jsonable(rate_card),
            cost_by_year=_jsonable(cost_by_year),
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

    def _compute(self, deploy_start, deploy_end, quantity, rate_card, anchor):
        """Split the deployment window by CONTRACT YEAR and cost each year at its
        own rate: for each year the window spans,
        ``quantity × rateCardByYear["Year-N"] × months-in-that-year``.
        Returns ``(total_months, cost_by_year, computed_cost)``. Contract-year
        boundaries are anchored on the project start date (``cf_pool`` buckets)."""
        start = resource_duration._as_date(deploy_start)
        end = resource_duration._as_date(deploy_end)
        a = resource_duration._as_date(anchor)
        if start is None or end is None or a is None or end < start:
            return Decimal("0"), {}, Decimal("0.00")

        qty = _dec(quantity)
        start_i = cf_pool.bucket_index(start, _YEARLY, anchor=a)
        end_i = cf_pool.bucket_index(end, _YEARLY, anchor=a)
        total_months = Decimal("0")
        cost_by_year: dict = {}
        total_cost = Decimal("0")
        for i in range(start_i, end_i + 1):
            bs, be = cf_pool.bucket_bounds(i, _YEARLY, anchor=a)
            seg_start = start if start > bs else bs
            seg_end = end if end < be else be
            months = resource_duration.duration_months(seg_start, seg_end)
            year_no = i + 1
            rate = _rate_for_year(rate_card, year_no)
            year_cost = (qty * rate * months).quantize(Decimal("0.01"))
            cost_by_year[f"Year-{year_no}"] = year_cost
            total_cost += year_cost
            total_months += months
        return (
            total_months.quantize(Decimal("0.01")),
            cost_by_year,
            total_cost.quantize(Decimal("0.01")),
        )

    def _repopulate_cost_item(self, cost_item_id: str) -> None:
        """Set the resource_cost row's ``cost`` to the SUM of its live planned
        resources — the derived planned resource cost for the phase."""
        total = self.repo.sum_cost_for_cost_item(cost_item_id)
        cost_item = self.cost_items.get_by_id(cost_item_id)
        if cost_item is not None:
            self.cost_items.update(cost_item, cost=total)

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
