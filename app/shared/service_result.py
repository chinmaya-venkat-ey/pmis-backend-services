"""Service result wrapper — ported verbatim from the monolith.

Lets services return success/failure without raising, making business
logic clearer and error handling explicit at the controller layer.
"""
from dataclasses import dataclass
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class ServiceResult(Generic[T]):
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    details: Optional[dict] = None

    @classmethod
    def ok(cls, data: T) -> "ServiceResult[T]":
        return cls(success=True, data=data)

    @classmethod
    def fail(
        cls, error: str, error_type: str = "error", details: Optional[dict] = None,
    ) -> "ServiceResult[T]":
        return cls(success=False, error=error, error_type=error_type, details=details)

    def is_success(self) -> bool:
        return self.success

    def is_failure(self) -> bool:
        return not self.success
