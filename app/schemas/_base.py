"""Shared Pydantic base for API response models.

``ResponseModel`` ensures every tz-aware ``datetime`` field on a response
serializes with the IST (``+05:30``) offset, regardless of what the DB
driver returned. Naive datetimes are left untouched (treated as request
input that should round-trip exactly).

Use this as the base for any schema that flows to the wire. Sub-schemas
embedded in a response (resource sidecars, attachment metadata, etc.)
should also subclass it so nested datetimes get the same treatment.

Centralised IST handling — relies on ``app.utilities.timezones.IST``
(no duplication of the offset constant).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.utilities.timezones import IST


class ResponseModel(BaseModel):
    """BaseModel + IST coercion for every tz-aware datetime field.

    The validator runs in ``mode='after'`` so it sees the fully-parsed
    fields (whether populated from ORM attributes via ``from_attributes``
    or from a JSON body). Only tz-aware values are converted — naive
    datetimes pass through unchanged so request payloads aren't silently
    shifted.
    """

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _coerce_datetimes_to_ist(self):
        for name in type(self).model_fields:
            value = getattr(self, name, None)
            if isinstance(value, datetime) and value.tzinfo is not None:
                object.__setattr__(self, name, value.astimezone(IST))
        return self
