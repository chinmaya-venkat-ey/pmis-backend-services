"""Resource-type catalog queries."""
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models.resource_type import ResourceTypeModel
from ....domain.resource_types.resource_type import ResourceType


def _to_domain(m: ResourceTypeModel) -> ResourceType:
    return ResourceType(
        id=m.id,
        code=m.code,
        name=m.name,
        active=bool(m.active),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


class ResourceTypeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, code: str, name: str, active: bool = True) -> ResourceType:
        m = ResourceTypeModel(code=code.strip().lower(), name=name.strip(), active=active)
        self.db.add(m)
        self.db.flush()
        return _to_domain(m)

    def get_by_id(self, rt_id: str) -> Optional[ResourceType]:
        m = self.db.query(ResourceTypeModel).filter(ResourceTypeModel.id == rt_id).first()
        return _to_domain(m) if m else None

    def get_by_code(self, code: str) -> Optional[ResourceType]:
        m = (
            self.db.query(ResourceTypeModel)
            .filter(ResourceTypeModel.code == code.lower())
            .first()
        )
        return _to_domain(m) if m else None

    def exists_by_code(self, code: str) -> bool:
        return (
            self.db.query(ResourceTypeModel.id)
            .filter(ResourceTypeModel.code == code.lower())
            .first()
            is not None
        )

    def list_active(self) -> List[ResourceType]:
        rows = (
            self.db.query(ResourceTypeModel)
            .filter(ResourceTypeModel.active == True)  # noqa: E712
            .order_by(ResourceTypeModel.code.asc())
            .all()
        )
        return [_to_domain(r) for r in rows]

    def is_active(self, rt_id: str) -> bool:
        row = (
            self.db.query(ResourceTypeModel.active)
            .filter(ResourceTypeModel.id == rt_id)
            .first()
        )
        return bool(row and row[0])

    # ---- Admin CRUD (doc 20: /api/v3/master/resource_types) --------------

    def list_all(self) -> List[ResourceType]:
        """Every resource_type row including soft-disabled ones — for admin
        views. Stable order matches list_active so admins and pickers see
        rows in the same sequence."""
        rows = (
            self.db.query(ResourceTypeModel)
            .order_by(ResourceTypeModel.code.asc())
            .all()
        )
        return [_to_domain(r) for r in rows]

    def get_model_by_id(self, rt_id: str) -> Optional[ResourceTypeModel]:
        """Return the raw model (not domain) for callers that need to mutate
        the row inside their own transaction."""
        return (
            self.db.query(ResourceTypeModel)
            .filter(ResourceTypeModel.id == rt_id)
            .first()
        )

    def update(
        self,
        rt_id: str,
        *,
        name: Optional[str] = None,
    ) -> Optional[ResourceType]:
        """Patch the human-readable ``name`` on a resource type.

        ``code`` is NOT updatable — every activity_resource row in the
        system points at the row's id, but the picker dropdown is keyed
        by code; renaming a code mid-flight would break dropdown
        consistency for resource activities created with the old code.
        Renames go through deactivate-and-create-new, by design.

        Returns the updated row, or None if not found. Caller commits.
        """
        m = self.get_model_by_id(rt_id)
        if m is None:
            return None
        if name is not None:
            m.name = name.strip()
        self.db.flush()
        return _to_domain(m)

    def set_active(self, rt_id: str, active: bool) -> Optional[ResourceType]:
        """Soft-delete (active=False) or restore (active=True) a row.

        Existing activity_resource rows referencing this type continue to
        resolve via ``get_by_id`` — only the picker (``list_active``) and
        the create-time ``is_active`` validator filter on it. Caller
        commits.
        """
        m = self.get_model_by_id(rt_id)
        if m is None:
            return None
        m.active = bool(active)
        self.db.flush()
        return _to_domain(m)
