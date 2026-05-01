"""
Project repository for database operations.

Writes (create/update/soft_delete/hard_delete) do NOT commit. Callers own the
transaction boundary and must call ``db.commit()`` after the full operation
succeeds.

IDs are UUID strings (String(36)). projects.id IS the UUID — there is no
separate uuid column.
"""
from typing import Optional, List, Tuple
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ..models.project import ProjectModel
from ....domain.projects.project import Project
from ....shared.project_code import generate_project_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dialect_insert(db: Session):
    """Return the dialect-specific insert() construct that supports
    on_conflict_do_update() (PostgreSQL or SQLite)."""
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
        return _insert
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as _insert
        return _insert
    raise NotImplementedError(
        f"Upsert is not supported for dialect '{dialect}'. "
        "Only PostgreSQL and SQLite are supported."
    )


class ProjectRepository:
    """Repository for Project database operations."""

    def __init__(self, db: Session):
        self.db = db

    def _to_domain(self, model: ProjectModel, *, with_vendors: bool = True) -> Project:
        p = Project(
            id=model.id,
            project_code=model.project_code,
            name=model.name,
            description=model.description,
            active=model.active,
            public=model.public,
            status_explanation=model.status_explanation,
            created_at=model.created_at,
            updated_at=model.updated_at,
            parent_id=model.parent_id,
            status=model.status,
            owner=model.owner,
            category=model.category,
            start_date=model.start_date,
            end_date=model.end_date,
            actual_start_date=model.actual_start_date,
            actual_end_date=model.actual_end_date,
            is_version=bool(model.is_version),
            version_of=model.version_of,
            baseline_id=model.baseline_id,
            version_no=model.version_no,
            created_by=model.created_by,
            updated_by=model.updated_by,
            deleted_at=model.deleted_at,
            deleted_by=model.deleted_by,
            category_other=getattr(model, "category_other", None),
            category_other_reason=getattr(model, "category_other_reason", None),
            owner_other=getattr(model, "owner_other", None),
        )
        if with_vendors:
            # Lazy-load the vendor pairs. Cheap join; safe on every read path.
            from .vendor_repository import VendorRepository
            p.vendors = VendorRepository(self.db).list_project_vendors(model.id)
        return p

    # ------------------------------------------------------------------
    # writes — no commit except in upsert; caller owns transaction boundary
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        active: bool = True,
        public: bool = False,
        status_explanation: Optional[str] = None,
        parent_id: Optional[str] = None,
        status: str = "new",
        owner: Optional[str] = None,
        category: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        actual_start_date: Optional[datetime] = None,
        actual_end_date: Optional[datetime] = None,
        is_version: bool = False,
        version_of: Optional[str] = None,
        baseline_id: Optional[str] = None,
        version_no: Optional[int] = None,
        created_by: Optional[int] = None,
        # Caller may inject a pre-computed id (e.g. from the URL path of a
        # PUT upsert call). If omitted, a fresh uuid4 is generated.
        id: Optional[str] = None,
        # Caller may inject a pre-computed project_code (rare). If omitted,
        # a unique one is generated at IST-seconds precision.
        project_code: Optional[str] = None,
        category_other: Optional[str] = None,
        category_other_reason: Optional[str] = None,
        owner_other: Optional[str] = None,
    ) -> Project:
        if id is None:
            id = str(uuid4())
        if project_code is None:
            project_code = generate_project_code(self.db)

        model = ProjectModel(
            id=id,
            project_code=project_code,
            name=name,
            description=description,
            active=active,
            public=public,
            status_explanation=status_explanation,
            parent_id=parent_id,
            status=status,
            owner=owner,
            owner_other=owner_other,
            category=category,
            category_other=category_other,
            category_other_reason=category_other_reason,
            start_date=start_date,
            end_date=end_date,
            actual_start_date=actual_start_date,
            actual_end_date=actual_end_date,
            is_version=is_version,
            version_of=version_of,
            baseline_id=baseline_id,
            version_no=version_no,
            created_by=created_by,
            updated_by=created_by,
        )
        self.db.add(model)
        self.db.flush()
        return self._to_domain(model, with_vendors=False)

    def upsert_by_id(
        self,
        id: str,
        *,
        name: str,
        description: Optional[str] = None,
        active: bool = True,
        public: bool = False,
        status_explanation: Optional[str] = None,
        parent_id: Optional[str] = None,
        status: str = "new",
        owner: Optional[str] = None,
        category: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        category_other: Optional[str] = None,
        category_other_reason: Optional[str] = None,
        owner_other: Optional[str] = None,
    ) -> Tuple[Project, bool]:
        """
        Insert a project if no row with this id exists; otherwise update the
        existing row. Atomic via INSERT ... ON CONFLICT (id) DO UPDATE.

        Generates a project_code on insert; never overwrites it on update.
        id, project_code, and created_at are never overwritten; updated_at
        is bumped.

        Returns:
            (project, created) — created=True on fresh insert, False on update.

        Commits on success (unlike other writes) to preserve ON CONFLICT
        atomicity the wizard flow depends on.
        """
        insert_fn = _dialect_insert(self.db)
        now = _utcnow()

        existing = (
            self.db.query(ProjectModel.id)
            .filter(ProjectModel.id == id)
            .first()
        )
        existed_before = existing is not None

        new_project_code = None if existed_before else generate_project_code(self.db)

        values = dict(
            id=id,
            project_code=new_project_code or "__placeholder__",
            name=name,
            description=description,
            active=active,
            public=public,
            status_explanation=status_explanation,
            parent_id=parent_id,
            status=status,
            owner=owner,
            owner_other=owner_other,
            category=category,
            category_other=category_other,
            category_other_reason=category_other_reason,
            start_date=start_date,
            end_date=end_date,
            created_at=now,
            updated_at=now,
        )
        stmt = insert_fn(ProjectModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "name": stmt.excluded.name,
                "description": stmt.excluded.description,
                "active": stmt.excluded.active,
                "public": stmt.excluded.public,
                "status_explanation": stmt.excluded.status_explanation,
                "parent_id": stmt.excluded.parent_id,
                "status": stmt.excluded.status,
                "owner": stmt.excluded.owner,
                "owner_other": stmt.excluded.owner_other,
                "category": stmt.excluded.category,
                "category_other": stmt.excluded.category_other,
                "category_other_reason": stmt.excluded.category_other_reason,
                "start_date": stmt.excluded.start_date,
                "end_date": stmt.excluded.end_date,
                "updated_at": now,
                # id, project_code, created_at intentionally preserved.
            },
        )

        self.db.execute(stmt)
        self.db.commit()

        model = (
            self.db.query(ProjectModel)
            .filter(ProjectModel.id == id)
            .first()
        )
        return self._to_domain(model), (not existed_before)

    def update(
        self,
        project_id: str,
        *,
        updated_by: Optional[int] = None,
        include_deleted: bool = False,
        **fields,
    ) -> Optional[Project]:
        """Apply a field patch. Only known model attributes are applied."""
        q = self.db.query(ProjectModel).filter(ProjectModel.id == project_id)
        if not include_deleted:
            q = q.filter(ProjectModel.deleted_at.is_(None))
        model = q.first()
        if not model:
            return None

        # Immutable fields are never accepted via update().
        _IMMUTABLE = {"id", "project_code", "created_at", "created_by"}
        for attr, value in fields.items():
            if attr in _IMMUTABLE:
                continue
            if value is None:
                continue
            if hasattr(model, attr):
                setattr(model, attr, value)

        if updated_by is not None:
            model.updated_by = updated_by

        self.db.flush()
        return self._to_domain(model)

    def soft_delete(
        self,
        project_id: str,
        actor_id: Optional[int],
        when: Optional[datetime] = None,
    ) -> Optional[Project]:
        """Mark a project deleted. Idempotent on already-deleted rows."""
        model = (
            self.db.query(ProjectModel)
            .filter(ProjectModel.id == project_id)
            .first()
        )
        if not model:
            return None
        if model.deleted_at is None:
            model.deleted_at = when or _utcnow()
            model.deleted_by = actor_id
            self.db.flush()
        return self._to_domain(model)

    def hard_delete(self, project_id: str) -> bool:
        """Remove a row. Reserved for tests or admin cleanup — prefer soft_delete."""
        model = (
            self.db.query(ProjectModel)
            .filter(ProjectModel.id == project_id)
            .first()
        )
        if not model:
            return False
        self.db.delete(model)
        self.db.flush()
        return True

    # ------------------------------------------------------------------
    # reads — filter soft-deleted by default
    # ------------------------------------------------------------------

    def _base_query(self, include_deleted: bool = False):
        q = self.db.query(ProjectModel)
        if not include_deleted:
            q = q.filter(ProjectModel.deleted_at.is_(None))
        return q

    def get_by_id(self, project_id: str, include_deleted: bool = False) -> Optional[Project]:
        model = self._base_query(include_deleted).filter(ProjectModel.id == project_id).first()
        return self._to_domain(model) if model else None

    def get_by_project_code(self, project_code: str, include_deleted: bool = False) -> Optional[Project]:
        model = (
            self._base_query(include_deleted)
            .filter(ProjectModel.project_code == project_code)
            .first()
        )
        return self._to_domain(model) if model else None

    def list_all(self, offset: int = 0, limit: int = 20) -> Tuple[List[Project], int]:
        q = self._base_query()
        total = q.with_entities(func.count(ProjectModel.id)).scalar()
        models = q.offset(offset).limit(limit).all()
        return [self._to_domain(m) for m in models], total

    def list_active(self, offset: int = 0, limit: int = 20) -> Tuple[List[Project], int]:
        q = self._base_query().filter(ProjectModel.active == True)  # noqa: E712
        total = q.with_entities(func.count(ProjectModel.id)).scalar()
        models = q.offset(offset).limit(limit).all()
        return [self._to_domain(m) for m in models], total

    def list_public(self, offset: int = 0, limit: int = 20) -> Tuple[List[Project], int]:
        q = self._base_query().filter(ProjectModel.public == True)  # noqa: E712
        total = q.with_entities(func.count(ProjectModel.id)).scalar()
        models = q.offset(offset).limit(limit).all()
        return [self._to_domain(m) for m in models], total

    def exists_by_id(self, project_id: str) -> bool:
        return (
            self.db.query(ProjectModel.id)
            .filter(ProjectModel.id == project_id)
            .first()
            is not None
        )

    # ------------------------------------------------------------------
    # version helpers
    # ------------------------------------------------------------------

    def active_version_exists(self, baseline_id: str) -> bool:
        """Any version of ``baseline_id`` that is not suspended or deleted."""
        return (
            self.db.query(ProjectModel.id)
            .filter(
                and_(
                    ProjectModel.version_of == baseline_id,
                    ProjectModel.is_version == True,  # noqa: E712
                    ProjectModel.status != "suspended",
                    ProjectModel.deleted_at.is_(None),
                )
            )
            .first()
            is not None
        )

    def next_version_no(self, baseline_id: str) -> int:
        """Next sequential version number for a baseline (1-indexed)."""
        max_no = (
            self.db.query(func.max(ProjectModel.version_no))
            .filter(ProjectModel.version_of == baseline_id)
            .scalar()
        )
        return (max_no or 0) + 1

    def list_live_version_ids(self, baseline_id: str) -> List[str]:
        """Return the ids of every non-deleted version row for this baseline.

        Used by the delete flow to cascade a baseline-level soft-delete down
        to its versions. Includes versions in any status (including
        'suspended') so long as they aren't already soft-deleted.
        """
        rows = (
            self.db.query(ProjectModel.id)
            .filter(
                and_(
                    ProjectModel.version_of == baseline_id,
                    ProjectModel.is_version == True,  # noqa: E712
                    ProjectModel.deleted_at.is_(None),
                )
            )
            .all()
        )
        return [r[0] for r in rows]
