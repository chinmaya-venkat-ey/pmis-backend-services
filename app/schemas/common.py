"""Shared schemas: pagination envelope used by route handlers."""
from __future__ import annotations

from typing import Generic, List, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated envelope. For HAL Collection responses, use
    ``app.core.response.hal_collection`` in the handler instead."""

    items: List[T]
    total: int
    offset: int = 1
    page_size: int = 20
