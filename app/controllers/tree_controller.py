"""TreeController — thin facade in front of ``TreeService``.

One endpoint: full M/A/T/S tree under a project. The route gates with
``require_project_permission(PROJECTS_READ)`` — no further checks here.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.services.tree_service import TreeService


class TreeController:
    def __init__(self, db: Session):
        self.db = db
        self.service = TreeService(db)

    def get_tree(
        self, project_id: str, *, include_deleted: bool = False,
        caller_vendor_id=None, caller_is_admin: bool = True,
    ) -> Dict[str, Any]:
        return self.service.get_project_tree(
            project_id, include_deleted=include_deleted,
            caller_vendor_id=caller_vendor_id, caller_is_admin=caller_is_admin,
        )
