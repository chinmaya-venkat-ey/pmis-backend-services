"""Base Pydantic models for pmis-file-store.

All response models inherit ResponseModel to get IST timezone coercion
and camelCase alias generation (aliases used for HAL envelope output).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_serializer
from pydantic.alias_generators import to_camel

from app.utilities.timezones import IST


class ResponseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_datetime(self, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(IST).isoformat()
        return value
