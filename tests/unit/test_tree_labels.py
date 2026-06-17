"""Unit tests for the tree label index after switching to stored position
and adding cross-project label resolution.

- Labels use the STORED position (gap-preserving), matching the controllers /
  resolver / FE-echo — not a dense rank.
- Cross-project dep targets resolve to "ProjectName · <code>" via the
  cross-project fallback; the edge loader keeps live cross-project targets and
  prunes deleted ones.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.models.activity import Activity
from app.models.activity_dependency import ActivityDependency
from app.services.tree_service import (
    KIND_ACTIVITY,
    TreeService,
    _LabelIndex,
    _index_activities,
    _index_milestones,
)


def _db_returns(rows):
    db = MagicMock()
    exec_mock = MagicMock()
    exec_mock.all.return_value = rows
    db.execute.return_value = exec_mock
    return db


# ----------------------------------------- stored-position labelling --------

def test_index_milestones_uses_stored_position_not_rank():
    # Live milestones at positions 1 and 3 (position 2 was deleted -> gap).
    db = _db_returns([("m1", 1), ("m3", 3)])
    idx = _LabelIndex()
    result = _index_milestones(db, "p1", idx)
    # Stored position => M1, M3 (NOT a dense-rank M1, M2).
    assert idx.milestone_id_to_label == {"m1": "M1", "m3": "M3"}
    assert result == {"m1": 1, "m3": 3}


def test_index_activities_uses_stored_position():
    db = _db_returns([("a1", 1, "m1"), ("a3", 3, "m1")])  # gap at 2
    idx = _LabelIndex()
    result = _index_activities(db, "p1", idx, {"m1": 2})  # milestone stored pos 2
    assert idx.activity_id_to_label == {"a1": "A2.1", "a3": "A2.3"}
    assert result == {"a1": (2, 1), "a3": (2, 3)}


def test_index_milestones_skips_zero_position():
    db = _db_returns([("m1", 1), ("m0", 0)])
    idx = _LabelIndex()
    _index_milestones(db, "p1", idx)
    assert idx.milestone_id_to_label == {"m1": "M1"}  # 0/None position skipped


# --------------------------------------- cross-project label fallback -------

def test_label_index_cross_project_fallback():
    idx = _LabelIndex()
    idx.activity_id_to_label = {"a-local": "A1.1"}
    idx.cross_project_id_to_label = {"a-remote": "Other Project · A2.3"}

    assert idx.labels_of(KIND_ACTIVITY, ["a-local"]) == ["A1.1"]
    assert idx.labels_of(KIND_ACTIVITY, ["a-remote"]) == ["Other Project · A2.3"]
    # mixed + truly-unknown dropped, input order preserved
    assert idx.labels_of(
        KIND_ACTIVITY, ["a-local", "a-remote", "a-unknown"],
    ) == ["A1.1", "Other Project · A2.3"]
    assert idx.label_of(KIND_ACTIVITY, "a-remote") == "Other Project · A2.3"
    assert idx.label_of(KIND_ACTIVITY, "a-unknown") is None


# ------------------------------- edge loader keeps live cross-project -------

def test_bulk_load_keeps_live_cross_project_and_prunes_deleted():
    svc = TreeService(MagicMock())
    edges = MagicMock()
    edges.all.return_value = [
        ("a1", "a2"),         # same-project (in live_tgt_ids)
        ("a1", "a-remote"),   # cross-project, live
        ("a1", "a-deleted"),  # cross-project, soft-deleted
    ]
    live_xproj = MagicMock()
    live_xproj.all.return_value = [("a-remote",)]  # only a-remote is live
    svc.db.execute = MagicMock(side_effect=[edges, live_xproj])

    out = svc._bulk_load_dep_edges(
        dep_model=ActivityDependency,
        from_col=ActivityDependency.from_activity_id,
        to_col=ActivityDependency.to_activity_id,
        live_src_ids={"a1"}, live_tgt_ids={"a2"},
        tgt_id_col=Activity.id, tgt_deleted_col=Activity.deleted_at,
    )
    assert out["a1"] == ["a2", "a-remote"]  # deleted cross-project dropped
