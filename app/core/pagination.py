"""Shared list pagination.

``page_size is None`` means "no pagination cap — return the whole result set".
A concrete ``page_size`` paginates as before (now uncapped at the route level).
The matching envelope handling lives in ``app.core.response.hal_collection``.
"""
from __future__ import annotations

from typing import Optional


def paginate(stmt, offset: int, page_size: Optional[int]):
    """Apply offset/limit to ``stmt`` unless ``page_size`` is None (return all)."""
    if page_size is None:
        return stmt
    return stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
