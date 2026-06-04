"""ProjectCostItemController — shapes Project-Cost responses (derived total
+ bound milestone ids)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.schemas.payment import CostItemResponse
from app.services.payment_page_service import _cost_item_response
from app.services.project_cost_item_service import ProjectCostItemService


class ProjectCostItemController:
    def __init__(self, db: Session):
        self.db = db
        self.service = ProjectCostItemService(db)
        self.repo = ProjectCostItemRepository(db)

    def _to_response(self, row) -> CostItemResponse:
        milestone_ids = getattr(row, "_milestone_ids", None)
        if milestone_ids is None:
            milestone_ids = self.repo.list_milestone_ids(row.id)
        return _cost_item_response(row, milestone_ids)

    def get(self, cost_item_id: str) -> CostItemResponse:
        return self._to_response(self.service.get_by_id(cost_item_id))

    def create(self, project_id, payload, *, caller_user_id, caller_is_admin=False) -> CostItemResponse:
        row = self.service.create(
            project_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._to_response(row)

    def update(self, cost_item_id, payload, *, caller_user_id, caller_is_admin=False) -> CostItemResponse:
        row = self.service.update(
            cost_item_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._to_response(row)

    def delete(self, cost_item_id, *, caller_user_id, caller_is_admin=False) -> None:
        self.service.delete(cost_item_id, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin)

    def restore(self, cost_item_id, *, caller_user_id, caller_is_admin=False) -> CostItemResponse:
        row = self.service.restore(
            cost_item_id, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )
        return self._to_response(row)

    def list_for_project(self, project_id, *, offset=1, page_size=50, include_deleted=False):
        rows, total = self.service.list_for_project(
            project_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        return {
            "items": [self._to_response(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def available_milestones(self, project_id, *, exclude_cost_item_id=None):
        rows = self.service.available_milestones(
            project_id, exclude_cost_item_id=exclude_cost_item_id,
        )
        return {
            "milestones": [
                {
                    "id": mid,
                    "display_code": f"M{pos}" if pos else None,
                    "name": name,
                }
                for mid, pos, name in rows
            ],
        }
