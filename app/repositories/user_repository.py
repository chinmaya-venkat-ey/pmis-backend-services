"""UserRepository — User CRUD + scoped queries.

Implements:
  - Standard get_by_{id,login,email}
  - `list_` with Doc-46 non-admin vendor auto-filter + admin-tier NOT-EXISTS exclusion
  - Soft-delete + restore (deleted_at + deleted_by)
  - Refresh-token rotation with the previous-jti grace window
  - check-login-available (case-sensitive)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.core.permissions import ADMIN_ROLE, SUPER_ADMIN_ROLE
from app.models.role import Role
from app.models.user import User
from app.models.user_role import UserRole
from app.models.user_role_assignment import UserRoleAssignment


_ADMIN_ROLE_NAMES = (ADMIN_ROLE, SUPER_ADMIN_ROLE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ lookups

    def get_by_id(self, user_id: str) -> Optional[User]:
        return self.db.get(User, user_id)

    def get_by_login(self, login: str, *, include_deleted: bool = False) -> Optional[User]:
        stmt = select(User).where(User.login == login)
        if not include_deleted:
            stmt = stmt.where(User.deleted_at.is_(None))
        return self.db.execute(stmt).scalars().first()

    def get_by_email(self, email: str, *, include_deleted: bool = False) -> Optional[User]:
        stmt = select(User).where(User.email == email)
        if not include_deleted:
            stmt = stmt.where(User.deleted_at.is_(None))
        return self.db.execute(stmt).scalars().first()

    def get_by_user_code(self, user_code: str) -> Optional[User]:
        return self.db.execute(
            select(User).where(User.user_code == user_code)
        ).scalars().first()

    def get_by_refresh_token_jti(self, jti: str) -> Optional[User]:
        """Look up the user whose current OR grace-window refresh_token_jti matches."""
        if not jti:
            return None
        now = _utcnow()
        stmt = select(User).where(
            or_(
                User.refresh_token_jti == jti,
                and_(
                    User.previous_refresh_token_jti == jti,
                    User.previous_refresh_token_jti_valid_until.is_not(None),
                    User.previous_refresh_token_jti_valid_until >= now,
                ),
            )
        )
        return self.db.execute(stmt).scalars().first()

    # ------------------------------------------------------------------ list with filters

    def list_(
        self,
        *,
        offset: int = 1,
        page_size: Optional[int] = None,
        status: Optional[str] = None,
        include_deleted: bool = False,
        vendor_id_filter: Optional[str] = None,
        exclude_admin_tier: bool = False,
    ) -> Tuple[List[User], int]:
        """List users with optional filters. Returns (rows, total).

        Doc-46:
          - `vendor_id_filter` narrows to one vendor (non-admin callers).
          - `exclude_admin_tier` removes users who hold admin or super_admin
            in EITHER legacy user_roles OR scoped user_role_assignments.

        Pagination is 1-based offset for FE compatibility.
        """
        base = select(User)
        count_base = select(func.count(User.id))

        if not include_deleted:
            base = base.where(User.deleted_at.is_(None))
            count_base = count_base.where(User.deleted_at.is_(None))

        if status:
            base = base.where(User.status == status)
            count_base = count_base.where(User.status == status)

        if vendor_id_filter is not None:
            base = base.where(User.vendor_id == vendor_id_filter)
            count_base = count_base.where(User.vendor_id == vendor_id_filter)

        if exclude_admin_tier:
            # NOT EXISTS subquery against either tier holding admin/super_admin
            admin_via_user_roles = exists().where(
                and_(
                    UserRole.user_id == User.id,
                    UserRole.role_id == Role.id,
                    Role.name.in_(_ADMIN_ROLE_NAMES),
                )
            )
            admin_via_assignments = exists().where(
                and_(
                    UserRoleAssignment.user_id == User.id,
                    UserRoleAssignment.role_id == Role.id,
                    Role.name.in_(_ADMIN_ROLE_NAMES),
                )
            )
            base = base.where(~admin_via_user_roles).where(~admin_via_assignments)
            count_base = count_base.where(~admin_via_user_roles).where(~admin_via_assignments)

        # FE convention: 1-based offset. Newest users first (Bug #2).
        zero_based = max(0, offset - 1)
        base = paginate(base.order_by(User.created_at.desc()), offset, page_size)

        rows = list(self.db.execute(base).scalars().all())
        total = self.db.execute(count_base).scalar_one()
        return rows, total

    # ------------------------------------------------------------------ writes

    def create(self, **kwargs) -> User:
        row = User(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: User, **kwargs) -> User:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def set_password(self, row: User, hashed_password: str) -> User:
        row.hashed_password = hashed_password
        self.db.flush()
        return row

    def soft_delete(self, row: User, *, deleted_by_user_id: str) -> User:
        row.deleted_at = _utcnow()
        row.deleted_by = deleted_by_user_id
        row.status = "inactive"
        self.db.flush()
        return row

    def restore(self, row: User) -> User:
        row.deleted_at = None
        row.deleted_by = None
        row.status = "active"
        self.db.flush()
        return row

    def rotate_refresh_token(
        self,
        row: User,
        *,
        new_jti: Optional[str],
        grace_seconds: int = 120,
    ) -> User:
        """Move current jti into the grace-window slot and stamp new_jti.

        `new_jti=None` clears the refresh state entirely (logout).
        """
        previous_jti = row.refresh_token_jti
        if previous_jti and grace_seconds > 0:
            row.previous_refresh_token_jti = previous_jti
            row.previous_refresh_token_jti_valid_until = _utcnow() + timedelta(seconds=grace_seconds)
        else:
            row.previous_refresh_token_jti = None
            row.previous_refresh_token_jti_valid_until = None
        row.refresh_token_jti = new_jti
        self.db.flush()
        return row

    def record_login(self, row: User, now: datetime) -> User:
        """Stamp a successful login: shift the prior login into
        ``previous_login_at`` (the "Last Login" the profile shows) and set
        ``last_login_at`` to this login. First-ever login leaves
        ``previous_login_at`` NULL."""
        row.previous_login_at = row.last_login_at
        row.last_login_at = now
        self.db.flush()
        return row
