from typing import Optional
from pydantic import BaseModel


class IntrospectRequest(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class IntrospectResponseActive(BaseModel):
    active: bool = True
    # user will be returned as domain object elsewhere (controller wraps)


class IntrospectResponseRotated(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
