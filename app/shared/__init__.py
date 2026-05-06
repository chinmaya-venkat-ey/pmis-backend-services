"""Shared utilities package."""
from .service_result import ServiceResult
from .pagination import PaginatedResult, calculate_offset

__all__ = [
    "ServiceResult",
    "PaginatedResult",
    "calculate_offset",
]
