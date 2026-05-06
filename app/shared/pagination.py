"""
Pagination utilities.
"""
from typing import TypeVar, Generic, List
from dataclasses import dataclass

T = TypeVar('T')


@dataclass
class PaginatedResult(Generic[T]):
    """
    Paginated result container.
    """

    items: List[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        """Calculate total number of pages."""
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    @property
    def has_next(self) -> bool:
        """Check if there is a next page."""
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        """Check if there is a previous page."""
        return self.page > 1


def calculate_offset(page: int, page_size: int) -> int:
    """
    Calculate database offset from page number.

    Args:
        page: Page number (1-indexed)
        page_size: Number of items per page

    Returns:
        Database offset (0-indexed)
    """
    return (page - 1) * page_size
