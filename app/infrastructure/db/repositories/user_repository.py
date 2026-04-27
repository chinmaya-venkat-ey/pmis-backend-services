"""User repository — ported from the monolith, API preserved 1:1.

Returns domain ``User`` dataclasses, not ORM models, so callers outside
the DB layer never touch SQLAlchemy classes.
"""
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ....domain.users.user import User
from ..models.user import UserModel


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def _to_domain(self, model: UserModel) -> User:
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
        )

    # ----- Create ---------------------------------------------------------

    def create(
        self,
        login: str,
        email: str,
        hashed_password: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        admin: bool = False,
        status: str = "active",
    ) -> User:
        user_model = UserModel(
            login=login,
            email=email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            admin=admin,
            status=status,
        )
        self.db.add(user_model)
        self.db.commit()
        self.db.refresh(user_model)
        return self._to_domain(user_model)

    # ----- Read -----------------------------------------------------------

    def get_by_id(self, user_id: int) -> Optional[User]:
        model = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        return self._to_domain(model) if model else None

    def get_by_login(self, login: str) -> Optional[User]:
        model = self.db.query(UserModel).filter(UserModel.login == login).first()
        return self._to_domain(model) if model else None

    def get_by_email(self, email: str) -> Optional[User]:
        model = self.db.query(UserModel).filter(UserModel.email == email).first()
        return self._to_domain(model) if model else None

    def get_password_hash(self, user_id: int) -> Optional[str]:
        model = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        return model.hashed_password if model else None

    def get_password_hash_by_login(self, login: str) -> Optional[str]:
        model = self.db.query(UserModel).filter(UserModel.login == login).first()
        return model.hashed_password if model else None

    def list(
        self, offset: int = 0, limit: int = 20, status: Optional[str] = None,
    ) -> Tuple[List[User], int]:
        query = self.db.query(UserModel)
        if status:
            query = query.filter(UserModel.status == status)
        total = query.count()
        models = query.offset(offset).limit(limit).all()
        return [self._to_domain(m) for m in models], total

    def exists_by_login(self, login: str) -> bool:
        return self.db.query(
            self.db.query(UserModel).filter(UserModel.login == login).exists()
        ).scalar()

    def exists_by_email(self, email: str) -> bool:
        return self.db.query(
            self.db.query(UserModel).filter(UserModel.email == email).exists()
        ).scalar()

    # ----- Update ---------------------------------------------------------

    def update(
        self,
        user_id: int,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        admin: Optional[bool] = None,
        status: Optional[str] = None,
    ) -> Optional[User]:
        model = self.db.query(UserModel).filter(UserModel.id == user_id).first()
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
        self.db.commit()
        self.db.refresh(model)
        return self._to_domain(model)

    def update_password(self, user_id: int, hashed_password: str) -> bool:
        model = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        if not model:
            return False
        model.hashed_password = hashed_password
        self.db.commit()
        return True

    # ----- Refresh-token metadata ----------------------------------------

    def update_refresh_token_metadata(
        self,
        user_id: int,
        jti: str,
        expires_at,
        expected_old_jti: Optional[str] = None,
    ) -> bool:
        """Atomic update of refresh token jti + expiry.

        When ``expected_old_jti`` is provided, the update only succeeds
        if the current stored jti matches — this blocks silent overwrite
        of an already-rotated token.
        """
        query = self.db.query(UserModel).filter(UserModel.id == user_id)
        if expected_old_jti is not None:
            query = query.filter(UserModel.refresh_token_jti == expected_old_jti)

        rows = query.update(
            {
                UserModel.refresh_token_jti: jti,
                UserModel.refresh_token_expires_at: expires_at,
            },
            synchronize_session=False,
        )
        if rows:
            self.db.commit()
            return True
        return False

    def get_refresh_metadata(self, user_id: int):
        """Returns ``(jti, expires_at)`` or ``(None, None)``."""
        model = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        if not model:
            return None, None
        return model.refresh_token_jti, model.refresh_token_expires_at

    # ----- Delete ---------------------------------------------------------

    def delete(self, user_id: int) -> bool:
        model = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        if not model:
            return False
        self.db.delete(model)
        self.db.commit()
        return True
