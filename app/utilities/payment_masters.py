"""Validation of payment master codes against the cross-schema mirrors.

The payment screen stores ``cost_type_code`` / ``frequency_code`` as plain
codes (logical FKs to masters.cost_types / masters.frequencies). These
helpers confirm a supplied code resolves to an ACTIVE master row, reading
the read-only mirrors declared in ``app/models/_cross_schema.py``. ``None``
is accepted (every value is optional for now).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.models._cross_schema import CostType as _CostTypeMirror
from app.models._cross_schema import Frequency as _FrequencyMirror


def validate_cost_type_code(db: Session, code: Optional[str]) -> Optional[str]:
    """Normalize + confirm a cost-type code is an active master. Returns the
    lowercased code, or ``None`` when not supplied."""
    if code is None:
        return None
    norm = code.strip().lower()
    if not norm:
        return None
    found = db.execute(
        select(_CostTypeMirror.code)
        .where(_CostTypeMirror.code == norm)
        .where(_CostTypeMirror.active.is_(True))
        .limit(1)
    ).first()
    if found is None:
        raise ValidationError(f"Unknown or inactive cost type: {code!r}")
    return norm


def validate_frequency_code(db: Session, code: Optional[str]) -> Optional[str]:
    """Normalize + confirm a frequency code is an active master. Returns the
    lowercased code, or ``None`` when not supplied."""
    if code is None:
        return None
    norm = code.strip().lower()
    if not norm:
        return None
    found = db.execute(
        select(_FrequencyMirror.code)
        .where(_FrequencyMirror.code == norm)
        .where(_FrequencyMirror.active.is_(True))
        .limit(1)
    ).first()
    if found is None:
        raise ValidationError(f"Unknown or inactive frequency: {code!r}")
    return norm
