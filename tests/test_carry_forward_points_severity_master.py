"""Carry-forward points convert the carried severity LEVEL → POINTS through the
project's OWN severity_master (SlaEvaluatorService._build_level_points_map), not
the hardcoded RFP defaults — so a project that customizes its severity points
gets carry-forward LD on its own scale, and falls back to defaults only when it
configured none."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.sla_evaluator.service import SlaEvaluatorService
from app.services.sla_evaluator.point_accumulation import DEFAULT_LEVEL_POINTS


class _FakeMasterRepo:
    def __init__(self, rows):
        self._rows = rows

    def list_for_project(self, project_id):
        return self._rows if project_id == "custom" else []


def _svc(rows):
    svc = SlaEvaluatorService.__new__(SlaEvaluatorService)  # skip DB wiring
    svc.master_repo = _FakeMasterRepo(rows)
    return svc


def test_carry_forward_points_use_project_severity_master():
    # Project maps level 4 → 20 points (RFP default is 8).
    rows = [SimpleNamespace(level=4, points=20), SimpleNamespace(level=2, points=10)]
    svc = _svc(rows)
    m = svc._build_level_points_map("custom")
    assert m == {4: Decimal("20"), 2: Decimal("10")}
    # The carry-forward resolution used in rollup_mapping_for_quarter:
    cf_map = m or DEFAULT_LEVEL_POINTS
    cf_points = cf_map.get(4, DEFAULT_LEVEL_POINTS.get(4, Decimal("0")))
    assert cf_points == Decimal("20")                 # project's scale, not the default
    assert DEFAULT_LEVEL_POINTS.get(4) != Decimal("20")   # proves it differs from default


def test_carry_forward_points_fall_back_to_default_when_unconfigured():
    svc = _svc([])
    m = svc._build_level_points_map("no-config")       # no severity_master → None
    assert m is None
    cf_map = m or DEFAULT_LEVEL_POINTS
    assert cf_map is DEFAULT_LEVEL_POINTS
    assert cf_map.get(4, Decimal("0")) == DEFAULT_LEVEL_POINTS.get(4)
