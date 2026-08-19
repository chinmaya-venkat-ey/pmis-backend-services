"""resource_classification is PER RESOURCE — it lives on each planned-resource
allocation (ActivityPlannedResourceItem), not on the activity. Defaults to
'planned', accepts 'additional', normalizes case, and rejects anything else."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.activity import ActivityPlannedResourceItem


def _item(**kw):
    base = dict(
        designation="Developer", quantity=1, duration=Decimal("2"),
        planned_deployment_date=date(2026, 4, 15),
    )
    base.update(kw)
    return ActivityPlannedResourceItem(**base)


def test_defaults_to_planned():
    assert _item().resource_classification == "planned"


def test_accepts_additional_and_normalizes_case():
    assert _item(resource_classification="Additional").resource_classification == "additional"


def test_explicit_none_becomes_planned():
    assert _item(resource_classification=None).resource_classification == "planned"


def test_rejects_invalid_value():
    with pytest.raises(ValidationError):
        _item(resource_classification="extra")


def test_activity_schemas_no_longer_carry_the_field():
    # the attribute moved off the activity-level request/response schemas
    from app.schemas.activity import (
        ActivityCreateRequest, ActivityUpdateRequest, ActivityResponse,
    )
    for model in (ActivityCreateRequest, ActivityUpdateRequest, ActivityResponse):
        assert "resource_classification" not in model.model_fields
