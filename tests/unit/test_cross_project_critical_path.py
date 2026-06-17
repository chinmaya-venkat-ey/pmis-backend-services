"""Cross-project critical path: an external predecessor is folded into the CPM
graph as a constraint node, so the UNCHANGED ``ES = max(EF of preds)+1``
formula pushes the dependent's Early Start. Externals are kept out of the
schedule/flow output and surfaced only in depends_on (flagged).
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from app.services.critical_path_service import CriticalPathService


# Future dates so _days_delayed (running-late accrual) never triggers.
A1_START, A1_END = datetime(2027, 1, 1), datetime(2027, 1, 6)    # 5 days
X_START, X_END = datetime(2027, 1, 1), datetime(2027, 1, 11)     # 10 days


def _activity(aid, mid, pos, start, end):
    return {
        "id": aid, "name": aid.upper(), "milestone_id": mid, "position": pos,
        "status": "not_completed", "start_date": start, "end_date": end,
        "actual_start_date": None, "actual_end_date": None,
    }


def _external(xid):
    return {
        "id": xid, "name": "EXT", "milestone_id": "mx", "position": 3,
        "status": "not_completed", "start_date": X_START, "end_date": X_END,
        "actual_start_date": None, "actual_end_date": None,
        "milestone_position": 2, "project_name": "Proj B",
        "_cross_project": True, "_project_name": "Proj B",
    }


def _svc(*, xproj):
    svc = CriticalPathService(MagicMock())
    svc.repo = MagicMock()
    svc.repo.get_project_activities.return_value = [
        _activity("a1", "m1", 1, A1_START, A1_END),
    ]
    svc.repo.get_project_milestones.return_value = {
        "m1": {"id": "m1", "name": "M one", "position": 1},
    }
    svc.repo.get_activity_dependencies.return_value = []
    svc.repo.get_cross_project_predecessors.return_value = xproj
    return svc


def test_cross_project_predecessor_pushes_early_start():
    svc = _svc(xproj=([("a1", "x1")], {"x1": _external("x1")}))
    result = svc.get_analysis("p1")

    # Only the in-project activity is in the schedule (external excluded).
    assert len(result.activity_schedule) == 1
    row = result.activity_schedule[0]
    assert row.activity_id == "a1"
    # X (dur 10) is a source: ES=1, EF=10 -> A1.ES = 10+1 = 11, EF = 11+5-1 = 15.
    assert row.early_start == 11
    assert row.early_finish == 15
    # The external predecessor is surfaced in depends_on, flagged + qualified.
    assert len(row.depends_on) == 1
    dep = row.depends_on[0]
    assert dep.activity_id == "x1"
    assert dep.cross_project is True
    assert dep.project_name == "Proj B"
    assert dep.display_code == "Proj B · A2.3"
    # Metadata counts in-project activities only.
    assert result.metadata.total_activities == 1
    # Flow diagram has only the in-project node, no dangling external edge.
    assert len(result.flow_diagram["nodes"]) == 1
    assert result.flow_diagram["edges"] == []


def test_no_cross_project_is_unchanged():
    svc = _svc(xproj=([], {}))
    result = svc.get_analysis("p1")
    row = result.activity_schedule[0]
    assert row.early_start == 1       # source, unchanged
    assert row.early_finish == 5
    assert row.depends_on == []
    assert result.metadata.total_activities == 1


def test_dependency_table_lists_cross_project_predecessor():
    svc = _svc(xproj=([("a1", "x1")], {"x1": _external("x1")}))
    result = svc.get_dependencies("p1")
    row = next(r for r in result.dependencies if r.activity_id == "a1")
    dep = next(d for d in row.depends_on if d.activity_id == "x1")
    assert dep.cross_project is True
    assert dep.project_name == "Proj B"
    assert dep.display_code == "Proj B · A2.3"
