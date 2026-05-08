"""
Service result wrapper for business logic operations.
"""
from typing import Generic, TypeVar, Optional, Any
from dataclasses import dataclass

T = TypeVar('T')


@dataclass
class ServiceResult(Generic[T]):
    """
    Result wrapper for service operations.

    This allows services to return success/failure without throwing exceptions,
    making business logic clearer and error handling more explicit.
    """

    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    details: Optional[dict] = None

    @classmethod
    def ok(cls, data: T) -> "ServiceResult[T]":
        """
        Create a successful result.

        Args:
            data: Result data

        Returns:
            ServiceResult with success=True
        """
        return cls(success=True, data=data)

    @classmethod
    def fail(
        cls,
        error: str,
        error_type: str = "error",
        details: Optional[dict] = None
    ) -> "ServiceResult[T]":
        """
        Create a failed result.

        Args:
            error: Error message
            error_type: Error type identifier
            details: Optional error details

        Returns:
            ServiceResult with success=False
        """
        return cls(
            success=False,
            error=error,
            error_type=error_type,
            details=details
        )

    def is_success(self) -> bool:
        """Check if result is successful."""
        return self.success

    def is_failure(self) -> bool:
        """Check if result is a failure."""
        return not self.success
