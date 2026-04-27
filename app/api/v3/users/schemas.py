"""User API schemas — request/response models.

Ported verbatim from the monolith so request/response shapes match.
"""
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserCreateRequest(BaseModel):
    login: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    firstName: Optional[str] = Field(None, max_length=255)
    lastName: Optional[str] = Field(None, max_length=255)
    admin: bool = False


class UserUpdateRequest(BaseModel):
    email: Optional[EmailStr] = None
    firstName: Optional[str] = Field(None, max_length=255)
    lastName: Optional[str] = Field(None, max_length=255)
    admin: Optional[bool] = None
    status: Optional[str] = None


class UserPasswordUpdateRequest(BaseModel):
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    login: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None


class UserListQuery(BaseModel):
    offset: int = Field(1, ge=1, description="Page number (1-indexed)")
    pageSize: int = Field(20, ge=1, le=100, description="Items per page")
    status: Optional[str] = Field(None, description="Filter by status")


class IntrospectRequest(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
