"""Role repository.

Doc 21 part B: the JSON ``permissions`` column on ``roles`` is gone.
Read paths join ``role_permissions`` to surface the current permission
set; write paths replace the join-table contents through
``RbacRepository.replace_role_permissions``.
"""
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from ....domain.roles.role import Role
from ..models.role import RoleModel
from ..models.role_permission import RolePermissionModel


class RoleRepository:
    def __init__(self, db: Session):
        self.db = db

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _to_domain(self, model: RoleModel) -> Role:
        codes = sorted(
            r[0]
            for r in self.db.query(RolePermissionModel.permission_code)
            .filter(RolePermissionModel.role_id == model.id)
            .all()
        )
        return Role(
            id=model.id,
            name=model.name,
            description=getattr(model, "description", None),
            permissions=codes,
            builtin=model.builtin,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    # -------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------

    def create(
        self, name: str, permissions: List[str],
        builtin: bool = False,
        description: Optional[str] = None,
    ) -> Role:
        from .rbac_repository import RbacRepository
        role = RoleModel(name=name, description=description, builtin=builtin)
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        if permissions:
            RbacRepository(self.db).replace_role_permissions(
                role.id, list(dict.fromkeys(permissions)),
            )
            self.db.commit()
        return self._to_domain(role)

    def get_by_id(self, role_id: int) -> Optional[Role]:
        m = self.db.query(RoleModel).filter(RoleModel.id == role_id).first()
        return self._to_domain(m) if m else None

    def get_by_name(self, name: str) -> Optional[Role]:
        m = self.db.query(RoleModel).filter(RoleModel.name == name).first()
        return self._to_domain(m) if m else None

    def list(self, offset: int = 0, limit: int = 20) -> Tuple[List[Role], int]:
        q = self.db.query(RoleModel)
        total = q.with_entities(func.count(RoleModel.id)).scalar() or 0
        rows = q.order_by(RoleModel.id.asc()).offset(offset).limit(limit).all()
        return [self._to_domain(r) for r in rows], total

    def update(
        self, role_id: int,
        name: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        description: Optional[str] = None,
    ) -> Optional[Role]:
        from .rbac_repository import RbacRepository
        m = self.db.query(RoleModel).filter(RoleModel.id == role_id).first()
        if not m:
            return None
        if name is not None:
            m.name = name
        if description is not None:
            m.description = description
        if permissions is not None:
            RbacRepository(self.db).replace_role_permissions(
                role_id, list(dict.fromkeys(permissions)),
            )
        self.db.commit()
        self.db.refresh(m)
        return self._to_domain(m)

    def delete(self, role_id: int) -> bool:
        from .rbac_repository import RbacRepository
        from sqlalchemy import delete as sql_delete
        from ..models.user_role import UserRoleModel
        m = self.db.query(RoleModel).filter(RoleModel.id == role_id).first()
        if not m:
            return False
        # Cascade: drop role-permission grants and user-role assignments.
        self.db.execute(
            sql_delete(RolePermissionModel).where(
                RolePermissionModel.role_id == role_id
            )
        )
        self.db.execute(
            sql_delete(UserRoleModel).where(UserRoleModel.role_id == role_id)
        )
        self.db.delete(m)
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
