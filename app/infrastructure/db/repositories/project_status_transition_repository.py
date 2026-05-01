"""Repository for the project_status_transitions catalog.

Reads + admin-curated CRUD via the consolidated ``/api/v3/master/project_status_transitions``
router (doc 20). The seed runs once at init_db time from the in-code
``_LEGAL_TRANSITIONS`` constant; CRUD operations let admins add new edges
or deactivate ones that should no longer be usable without a code change.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models.project_status_transition import ProjectStatusTransitionModel


class ProjectStatusTransitionRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- Reads -----------------------------------------------------------

    def list_active(self) -> List[ProjectStatusTransitionModel]:
        return (
            self.db.query(ProjectStatusTransitionModel)
            .filter(ProjectStatusTransitionModel.active.is_(True))
            .order_by(
                ProjectStatusTransitionModel.from_status.asc(),
                ProjectStatusTransitionModel.to_status.asc(),
            )
            .all()
        )

    def list_all(self) -> List[ProjectStatusTransitionModel]:
        """Every row including soft-disabled ones — for admin views."""
        return (
            self.db.query(ProjectStatusTransitionModel)
            .order_by(
                ProjectStatusTransitionModel.from_status.asc(),
                ProjectStatusTransitionModel.to_status.asc(),
            )
            .all()
        )

    def get_by_id(self, row_id: int) -> Optional[ProjectStatusTransitionModel]:
        return (
            self.db.query(ProjectStatusTransitionModel)
            .filter(ProjectStatusTransitionModel.id == row_id)
            .first()
        )

    def find_edge(
        self, from_status: Optional[str], to_status: str,
    ) -> Optional[ProjectStatusTransitionModel]:
        """Return the active row matching this edge, or None if missing."""
        q = (
            self.db.query(ProjectStatusTransitionModel)
            .filter(ProjectStatusTransitionModel.to_status == to_status)
            .filter(ProjectStatusTransitionModel.active.is_(True))
        )
        if from_status is None:
            q = q.filter(ProjectStatusTransitionModel.from_status.is_(None))
        else:
            q = q.filter(ProjectStatusTransitionModel.from_status == from_status)
        return q.first()

    def find_edge_any(
        self, from_status: Optional[str], to_status: str,
    ) -> Optional[ProjectStatusTransitionModel]:
        """Same as find_edge but matches soft-disabled rows too. Used by
        the admin create endpoint to detect the "this edge already exists,
        just inactive — re-activate it" path."""
        q = (
            self.db.query(ProjectStatusTransitionModel)
            .filter(ProjectStatusTransitionModel.to_status == to_status)
        )
        if from_status is None:
            q = q.filter(ProjectStatusTransitionModel.from_status.is_(None))
        else:
            q = q.filter(ProjectStatusTransitionModel.from_status == from_status)
        return q.first()

    def known_to_statuses(self) -> List[str]:
        """Distinct ``to_status`` values across active rows.

        The set of statuses the API recognises is exactly this list — used
        by the create-project validator to reject typos like 'inprogress'
        with ``invalid_status`` rather than letting them through.
        """
        rows = (
            self.db.query(ProjectStatusTransitionModel.to_status)
            .filter(ProjectStatusTransitionModel.active.is_(True))
            .distinct()
            .all()
        )
        return sorted({r[0] for r in rows})

    # ---- Writes (doc 20) -------------------------------------------------

    def create(
        self,
        *,
        from_status: Optional[str],
        to_status: str,
        requires_admin: bool = False,
        version_only: bool = False,
        description: Optional[str] = None,
    ) -> ProjectStatusTransitionModel:
        """Add a new ``(from_status, to_status)`` edge. Caller commits.

        The unique constraint on ``(from_status, to_status)`` rejects
        duplicates at the DB layer; the route checks via
        ``find_edge_any`` first to give a friendlier 409 message.
        """
        row = ProjectStatusTransitionModel(
            from_status=from_status,
            to_status=to_status,
            requires_admin=bool(requires_admin),
            version_only=bool(version_only),
            active=True,
            description=description,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def update(
        self,
        row_id: int,
        *,
        requires_admin: Optional[bool] = None,
        version_only: Optional[bool] = None,
        description: Optional[str] = None,
    ) -> Optional[ProjectStatusTransitionModel]:
        """Patch the policy fields on an edge.

        ``from_status`` / ``to_status`` are the row's identity — patching
        them would amount to deleting one edge and creating another. The
        route schema omits them; this method ignores them too.

        Returns the updated row or None if not found. Caller commits.
        """
        row = self.get_by_id(row_id)
        if row is None:
            return None
        if requires_admin is not None:
            row.requires_admin = bool(requires_admin)
        if version_only is not None:
            row.version_only = bool(version_only)
        if description is not None:
            row.description = description
        self.db.flush()
        return row

    def set_active(
        self, row_id: int, active: bool,
    ) -> Optional[ProjectStatusTransitionModel]:
        """Soft-delete (active=False) or restore (active=True) an edge.

        Returns the row or None if not found. Caller commits.
        """
        row = self.get_by_id(row_id)
        if row is None:
            return None
        row.active = bool(active)
        self.db.flush()
        return row
