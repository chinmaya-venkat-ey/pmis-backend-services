"""Unit tests for DivisionService — the canonical active=False catalog pattern.

Doesn't hit the DB. Exercises the conflict + not-found error paths and confirms
that is_builtin does NOT block delete (per user direction).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.schemas.division import DivisionCreateRequest, DivisionUpdateRequest


def _make_division(*, code="tmd1", is_builtin=False, active=True):
    """Build a stand-in for a Division ORM row."""
    row = MagicMock(name=f"Division({code})")
    row.id = 1
    row.code = code
    row.label = "Default"
    row.is_builtin = is_builtin
    row.requires_other = False
    row.active = active
    row.email = "div@example.com"
    row.phone_number = "+910000000000"
    return row


def test_create_division_conflict_when_code_exists():
    from app.services.division_service import DivisionService

    db = MagicMock()
    svc = DivisionService(db)
    svc.repo.get_by_code = MagicMock(return_value=_make_division(code="tmd1"))

    with pytest.raises(CatalogEntryConflictError) as exc_info:
        svc.create(DivisionCreateRequest(
            code="tmd1",
            label="Duplicate",
            email="x@y.com",
            phone_number="+910000000000",
        ))
    assert "tmd1" in exc_info.value.message
    assert exc_info.value.code == "CATALOG_ENTRY_CONFLICT"


def test_get_by_code_not_found():
    from app.services.division_service import DivisionService

    db = MagicMock()
    svc = DivisionService(db)
    svc.repo.get_by_code = MagicMock(return_value=None)

    with pytest.raises(CatalogEntryNotFoundError):
        svc.get_by_code("nope")


def test_delete_does_not_block_builtin():
    """Per user direction: is_builtin is informational only — deletes proceed."""
    from app.services.division_service import DivisionService

    db = MagicMock()
    svc = DivisionService(db)
    builtin_row = _make_division(code="tmd1", is_builtin=True)
    svc.repo.get_by_code = MagicMock(return_value=builtin_row)
    svc.repo.deactivate = MagicMock(return_value=builtin_row)

    result = svc.delete("tmd1")
    assert result is builtin_row
    svc.repo.deactivate.assert_called_once_with(builtin_row)
    db.commit.assert_called_once()


def test_update_passes_only_set_fields():
    from app.services.division_service import DivisionService

    db = MagicMock()
    svc = DivisionService(db)
    row = _make_division()
    svc.repo.get_by_code = MagicMock(return_value=row)
    svc.repo.update = MagicMock(return_value=row)

    svc.update("tmd1", DivisionUpdateRequest(label="New Label"))

    # Only `label` should be passed to repo.update; other fields stay defaults.
    update_kwargs = svc.repo.update.call_args.kwargs
    assert update_kwargs == {"label": "New Label"}
