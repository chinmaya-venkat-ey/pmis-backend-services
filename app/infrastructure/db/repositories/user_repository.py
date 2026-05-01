"""User repository for database operations.

Soft-delete is the default — every read filters ``deleted_at IS NULL``
unless ``include_deleted=True`` is passed (admin/audit paths only).

The list/get-by-id paths also LEFT JOIN ``vendors`` for the embedded
vendor name, and run a follow-up query against ``project_members ⋈
projects`` to embed the user's mapped projects (excluding closed and
soft-deleted projects) without N+1 lookups in the controller layer.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ....domain.users.user import User
from ..models.project import ProjectModel
from ..models.project_member import ProjectMemberModel
from ..models.user import UserModel
from ..models.vendor import VendorModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Project statuses that are FILTERED OUT of the user's mapped-projects
# list in API responses. Closed projects are "history"; soft-deleted ones
# never appear in the UI. The mapping rows themselves stay in the DB.
_HIDDEN_PROJECT_STATUSES = ("closed",)


class UserRepository:
    """Repository for User database operations."""

    def __init__(self, db: Session):
        self.db = db

    # ---- Conversion helpers --------------------------------------------

    def _to_domain(
        self,
        model: UserModel,
        vendor: Optional[VendorModel] = None,
        projects: Optional[List[dict]] = None,
    ) -> User:
        return User(
            id=model.id,
            login=model.login,
            email=model.email,
            first_name=model.first_name,
            last_name=model.last_name,
            admin=model.admin,
            status=model.status,
            created_at=model.created_at,
            updated_at=model.updated_at,
            vendor_id=getattr(model, "vendor_id", None),
            vendor_name=vendor.name if vendor else None,
            division=getattr(model, "division", None),
            division_other=getattr(model, "division_other", None),
            deleted_at=getattr(model, "deleted_at", None),
            deleted_by=getattr(model, "deleted_by", None),
            projects=projects or [],
        )

    def _load_projects_for_user(self, user_id: int) -> List[dict]:
        """Return slim project dicts for embedding in user responses."""
        rows = (
            self.db.query(
                ProjectModel.id,
                ProjectModel.project_code,
                ProjectModel.name,
                ProjectModel.status,
            )
            .join(
                ProjectMemberModel,
                ProjectMemberModel.project_id == ProjectModel.id,
            )
            .filter(ProjectMemberModel.user_id == user_id)
            .filter(ProjectModel.deleted_at.is_(None))
            .filter(~ProjectModel.status.in_(_HIDDEN_PROJECT_STATUSES))
            .order_by(desc(ProjectModel.created_at), desc(ProjectModel.id))
            .all()
        )
        return [
            {
                "id": pid,
                "project_code": pcode,
                "name": pname,
                "status": pstatus,
            }
            for (pid, pcode, pname, pstatus) in rows
        ]

    def _load_vendor(self, vendor_id: Optional[str]) -> Optional[VendorModel]:
        if not vendor_id:
            return None
        return (
            self.db.query(VendorModel)
            .filter(VendorModel.id == vendor_id)
            .first()
        )

    # ---- Create --------------------------------------------------------

    def create(
        self,
        login: str,
        email: str,
        hashed_password: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        admin: bool = False,
        status: str = "active",
        vendor_id: Optional[str] = None,
        division: Optional[str] = None,
        division_other: Optional[str] = None,
    ) -> User:
        """Create a new user. Caller is responsible for committing."""
        user_model = UserModel(
            login=login,
            email=email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            admin=admin,
            status=status,
            vendor_id=vendor_id,
            division=division,
            division_other=division_other,
        )
        self.db.add(user_model)
        self.db.flush()
        vendor = self._load_vendor(user_model.vendor_id)
        return self._to_domain(user_model, vendor=vendor, projects=[])

    # ---- Read ----------------------------------------------------------

    def get_by_id(
        self, user_id: int, *, include_deleted: bool = False,
    ) -> Optional[User]:
        q = self.db.query(UserModel).filter(UserModel.id == user_id)
        if not include_deleted:
            q = q.filter(UserModel.deleted_at.is_(None))
        model = q.first()
        if not model:
            return None
        vendor = self._load_vendor(model.vendor_id)
        projects = self._load_projects_for_user(model.id)
        return self._to_domain(model, vendor=vendor, projects=projects)

    def get_by_login(
        self, login: str, *, include_deleted: bool = False,
    ) -> Optional[User]:
        q = self.db.query(UserModel).filter(UserModel.login == login)
        if not include_deleted:
            q = q.filter(UserModel.deleted_at.is_(None))
        model = q.first()
        if not model:
            return None
        vendor = self._load_vendor(model.vendor_id)
        projects = self._load_projects_for_user(model.id)
        return self._to_domain(model, vendor=vendor, projects=projects)

    def get_by_email(
        self, email: str, *, include_deleted: bool = False,
    ) -> Optional[User]:
        q = self.db.query(UserModel).filter(UserModel.email == email)
        if not include_deleted:
            q = q.filter(UserModel.deleted_at.is_(None))
        model = q.first()
        if not model:
            return None
        vendor = self._load_vendor(model.vendor_id)
        projects = self._load_projects_for_user(model.id)
        return self._to_domain(model, vendor=vendor, projects=projects)

    def get_password_hash(self, user_id: int) -> Optional[str]:
        """Used by login/auth — bypasses soft-delete filter (we want to
        reject login for inactive/deleted users with a dedicated message)."""
        model = (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .first()
        )
        return model.hashed_password if model else None

    def get_password_hash_by_login(self, login: str) -> Optional[str]:
        """Used by login flow. Bypasses soft-delete filter."""
        model = (
            self.db.query(UserModel)
            .filter(UserModel.login == login)
            .first()
        )
        return model.hashed_password if model else None

    def list(
        self,
        offset: int = 0,
        limit: int = 20,
        status: Optional[str] = None,
        *,
        include_deleted: bool = False,
    ) -> Tuple[List[User], int]:
        """List users — newest first, soft-deleted hidden by default."""
        query = self.db.query(UserModel)
        if not include_deleted:
            query = query.filter(UserModel.deleted_at.is_(None))
        if status:
            query = query.filter(UserModel.status == status)

        total = query.count()

        # Newest-first ordering. The id-DESC tiebreaker keeps pagination
        # stable when two rows share a created_at timestamp.
        models = (
            query.order_by(desc(UserModel.created_at), desc(UserModel.id))
            .offset(offset)
            .limit(limit)
            .all()
        )

        users = []
        for m in models:
            vendor = self._load_vendor(m.vendor_id)
            projects = self._load_projects_for_user(m.id)
            users.append(self._to_domain(m, vendor=vendor, projects=projects))

        return users, total

    def exists_by_login(self, login: str) -> bool:
        """Existence check — INCLUDES soft-deleted rows so we don't allow
        recycling a login that's still occupied by a tombstoned user."""
        return self.db.query(
            self.db.query(UserModel).filter(UserModel.login == login).exists()
        ).scalar()

    def exists_by_email(self, email: str) -> bool:
        return self.db.query(
            self.db.query(UserModel).filter(UserModel.email == email).exists()
        ).scalar()

    def has_other_active_admin(self, exclude_user_id: int) -> bool:
        """True if at least one OTHER active admin exists.

        "Active" = ``admin=True AND deleted_at IS NULL``. Used by the
        delete / update services to refuse the operation that would
        leave the system with zero active admins.
        """
        return (
            self.db.query(UserModel.id)
            .filter(UserModel.admin.is_(True))
            .filter(UserModel.deleted_at.is_(None))
            .filter(UserModel.id != exclude_user_id)
            .first()
            is not None
        )

    # ---- Update --------------------------------------------------------

    def update(
        self,
        user_id: int,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        admin: Optional[bool] = None,
        status: Optional[str] = None,
        vendor_id: Optional[str] = None,
        division: Optional[str] = None,
        division_other: Optional[str] = None,
        clear_division_other: bool = False,
        restore: bool = False,
    ) -> Optional[User]:
        """Apply a field patch.

        ``restore=True`` clears ``deleted_at`` / ``deleted_by`` — used when
        the service detects an admin setting status='active' on a
        currently-soft-deleted user OR via the dedicated /restore route.

        ``clear_division_other=True`` explicitly NULLs the division_other
        column (needed when division changes from 'others' to anything else
        — None means "leave as-is").
        """
        model = (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .first()
        )
        if not model:
            return None

        if email is not None:
            model.email = email
        if first_name is not None:
            model.first_name = first_name
        if last_name is not None:
            model.last_name = last_name
        if admin is not None:
            model.admin = admin
        if status is not None:
            model.status = status
        if vendor_id is not None:
            model.vendor_id = vendor_id
        if division is not None:
            model.division = division
        if division_other is not None:
            model.division_other = division_other
        if clear_division_other:
            model.division_other = None
        if restore:
            model.deleted_at = None
            model.deleted_by = None

        self.db.flush()
        vendor = self._load_vendor(model.vendor_id)
        projects = self._load_projects_for_user(model.id)
        return self._to_domain(model, vendor=vendor, projects=projects)

    def update_password(self, user_id: int, hashed_password: str) -> bool:
        model = (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .first()
        )
        if not model:
            return False
        model.hashed_password = hashed_password
        self.db.flush()
        return True

    # ---- Refresh-token rotation (with grace window) --------------------

    def rotate_refresh_token(
        self,
        user_id: int,
        new_jti: Optional[str],
        new_expires_at,
        grace_seconds: int = 0,
    ) -> bool:
        """Unconditional refresh-token rotation with grace-window capture.

        Reads the current ``refresh_token_jti`` and, if non-null, copies
        it into ``previous_refresh_token_jti`` with a TTL of
        ``grace_seconds``. Then writes ``new_jti`` + ``new_expires_at`` to
        the live columns.

        Both the previous-jti capture and the live-jti write happen in
        the same UPDATE statement so concurrent callers don't see torn
        state.

        Pass ``new_jti=None`` and ``grace_seconds=0`` from logout to
        clear everything (no grace after explicit logout).
        """
        model = (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .first()
        )
        if not model:
            return False

        if new_jti is None:
            # Explicit logout — clear current AND any in-flight grace.
            model.refresh_token_jti = None
            model.refresh_token_expires_at = None
            model.previous_refresh_token_jti = None
            model.previous_refresh_token_jti_valid_until = None
            self.db.commit()
            return True

        # Rotation: capture the outgoing jti as previous, then overwrite.
        outgoing = model.refresh_token_jti
        if outgoing is not None and grace_seconds > 0:
            model.previous_refresh_token_jti = outgoing
            model.previous_refresh_token_jti_valid_until = (
                _utcnow() + timedelta(seconds=grace_seconds)
            )
        model.refresh_token_jti = new_jti
        model.refresh_token_expires_at = new_expires_at
        self.db.commit()
        return True

    # Backward-compat shim. Old call sites still resolve to a working
    # rotation; ``expected_old_jti`` is now ignored — the atomic-swap
    # conditional was the source of the concurrent-refresh race that
    # the rewrite fixes.
    def update_refresh_token_metadata(
        self,
        user_id: int,
        jti: Optional[str],
        expires_at,
        expected_old_jti: Optional[str] = None,  # noqa: ARG002 — kept for compat
    ) -> bool:
        return self.rotate_refresh_token(
            user_id, jti, expires_at, grace_seconds=0,
        )

    def get_refresh_metadata(self, user_id: int):
        """Return ``(current_jti, current_expires_at)``.

        Kept for callers that don't need the grace-window fields.
        """
        model = (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .first()
        )
        if not model:
            return None, None
        return model.refresh_token_jti, model.refresh_token_expires_at

    def get_refresh_metadata_with_grace(self, user_id: int):
        """Return ``(current_jti, current_expires, previous_jti, previous_valid_until)``.

        Used by /refresh and /introspect to honour the grace window: a
        token whose jti matches ``previous_jti`` is still accepted while
        ``now() < previous_valid_until``.
        """
        model = (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .first()
        )
        if not model:
            return None, None, None, None
        return (
            model.refresh_token_jti,
            model.refresh_token_expires_at,
            model.previous_refresh_token_jti,
            model.previous_refresh_token_jti_valid_until,
        )

    # ---- Soft delete ---------------------------------------------------

    def soft_delete(self, user_id: int, actor_id: Optional[int]) -> bool:
        """Idempotent soft-delete. Sets deleted_at + deleted_by + status='inactive'.

        Returns True if a row was found, False otherwise.
        """
        model = (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .first()
        )
        if not model:
            return False
        if model.deleted_at is None:
            model.deleted_at = _utcnow()
            model.deleted_by = actor_id
            model.status = "inactive"
            self.db.flush()
        return True

    # Legacy method kept for backward compat — now delegates to soft_delete.
    def delete(self, user_id: int) -> bool:
        return self.soft_delete(user_id, actor_id=None)
