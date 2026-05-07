"""Priority repository (doc 41).

Same shape as the activity_status / milestone_status repos —
read-mostly catalog with admin-side CRUD and a soft-delete via
``active=False``. Built-in seed rows refuse the deactivate.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from ...db.models.priority import PriorityModel
from ....domain.priorities.priority import Priority


def _to_domain(m: PriorityModel) -> Priority:
    return Priority(
        id=m.id,
        code=m.code,
        name=m.name,
        description=m.description,
        position=m.position,
        active=bool(m.active),
        is_builtin=bool(m.is_builtin),
        created_at=m.created_at,
        updated_at=m.updated_at,
        deleted_at=m.deleted_at,
    )


class PriorityRepository:
    def __init__(self, db: Session):
        self.db = db

    # ----- reads -----
    def list_all(self, *, include_inactive: bool = False) -> List[Priority]:
        q = self.db.query(PriorityModel).filter(
            PriorityModel.deleted_at.is_(None),
        )
        if not include_inactive:
            q = q.filter(PriorityModel.active.is_(True))
        rows = q.order_by(
            PriorityModel.position.asc(),
            PriorityModel.code.asc(),
        ).all()
        return [_to_domain(r) for r in rows]

    def get_by_code(self, code: str) -> Optional[Priority]:
        m = (
            self.db.query(PriorityModel)
            .filter(PriorityModel.code == code)
            .first()
        )
        return _to_domain(m) if m else None

    def get_model_by_code(self, code: str) -> Optional[PriorityModel]:
        return (
            self.db.query(PriorityModel)
            .filter(PriorityModel.code == code)
            .first()
        )

    def is_active_code(self, code: str) -> bool:
        if not code:
            return False
        m = (
            self.db.query(PriorityModel.id)
            .filter(PriorityModel.code == code)
            .filter(PriorityModel.active.is_(True))
            .filter(PriorityModel.deleted_at.is_(None))
            .first()
        )
        return m is not None
