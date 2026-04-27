"""Role repository — ported from the monolith."""
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ....domain.roles.role import Role
from ..models.role import RoleModel


class RoleRepository:
    def __init__(self, db: Session):
        self.db = db

    def _to_domain(self, model: RoleModel) -> Role:
        return Role(
            id=model.id,
            name=model.name,
            permissions=model.permissions if isinstance(model.permissions, list) else [],
            builtin=model.builtin,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def create(self, name: str, permissions: List[str], builtin: bool = False) -> Role:
        model = RoleModel(name=name, permissions=permissions, builtin=builtin)
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return self._to_domain(model)

    def get_by_id(self, role_id: int) -> Optional[Role]:
        model = self.db.query(RoleModel).filter(RoleModel.id == role_id).first()
        return self._to_domain(model) if model else None

    def get_by_name(self, name: str) -> Optional[Role]:
        model = self.db.query(RoleModel).filter(RoleModel.name == name).first()
        return self._to_domain(model) if model else None

    def list(self, offset: int = 0, limit: int = 20) -> Tuple[List[Role], int]:
        query = self.db.query(RoleModel)
        total = query.count()
        models = query.offset(offset).limit(limit).all()
        return [self._to_domain(m) for m in models], total

    def update(
        self,
        role_id: int,
        name: Optional[str] = None,
        permissions: Optional[List[str]] = None,
    ) -> Optional[Role]:
        model = self.db.query(RoleModel).filter(RoleModel.id == role_id).first()
        if not model:
            return None
        if name is not None:
            model.name = name
        if permissions is not None:
            model.permissions = permissions
        self.db.commit()
        self.db.refresh(model)
        return self._to_domain(model)

    def delete(self, role_id: int) -> bool:
        model = self.db.query(RoleModel).filter(RoleModel.id == role_id).first()
        if not model:
            return False
        self.db.delete(model)
        self.db.commit()
        return True

    def exists_by_name(self, name: str) -> bool:
        return self.db.query(
            self.db.query(RoleModel).filter(RoleModel.name == name).exists()
        ).scalar()

    def exists_by_id(self, role_id: int) -> bool:
        return self.db.query(
            self.db.query(RoleModel).filter(RoleModel.id == role_id).exists()
        ).scalar()
