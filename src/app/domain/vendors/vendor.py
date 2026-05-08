"""Vendor domain entity."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from ...shared.datetime import iso_ist


@dataclass
class Vendor:
    id: str
    name: str
    description: Optional[str]
    active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None  # doc 26: UUID string
    # Contact details (doc 18). All three nullable; the FE renders an
    # empty cell when missing. None of them participate in soft-delete
    # / restore semantics — they're plain attributes.
    email: Optional[str] = None
    contact_person: Optional[str] = None
    phone_number: Optional[str] = None
    # Doc 25: human-readable identifier. Format
    # ``VN-{4-char-name-slug}-{YYMMDDHHMMSS-IST}``. Snapshot at create
    # time; never recomputed on rename. Optional on the dataclass for
    # back-compat with unit-test fixtures that may construct a Vendor
    # without a code; the migration backfills every persisted row.
    vendor_code: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "vendor_code": self.vendor_code,
            "name": self.name,
            "description": self.description,
            "active": self.active,
            "email": self.email,
            "contact_person": self.contact_person,
            "phone_number": self.phone_number,
            "created_at": iso_ist(self.created_at),
            "updated_at": iso_ist(self.updated_at),
            "deleted_at": iso_ist(self.deleted_at),
            "deleted_by": self.deleted_by,
        }
