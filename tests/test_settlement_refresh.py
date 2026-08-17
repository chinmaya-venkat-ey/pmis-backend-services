"""get_settlement's recompute gate: a missing / open / blocked_* row always
recomputes; refresh=True also recomputes a settled-but-stale row (auto_closed /
closed) so the net-payment page can pick up code/data fixes; overridden and
invoiced are frozen and never silently recomputed."""
from __future__ import annotations

from types import SimpleNamespace

from app.routes.settlement_routes import _recompute_or_existing


class _FakeSvc:
    def close(self, *a, **k):
        return SimpleNamespace(status="RECOMPUTED")


def _ran(status, refresh):
    existing = None if status is None else SimpleNamespace(status=status)
    row = _recompute_or_existing(
        _FakeSvc(), "p", None, existing, refresh=refresh, bearer_token=None,
    )
    return row.status == "RECOMPUTED"


def test_missing_open_blocked_always_recompute():
    for st in (None, "open", "blocked_missing_npqp", "blocked_missing_cap"):
        assert _ran(st, refresh=False) is True
        assert _ran(st, refresh=True) is True


def test_settled_rows_kept_unless_refresh():
    for st in ("auto_closed", "closed"):
        assert _ran(st, refresh=False) is False   # normal read keeps the stored row
        assert _ran(st, refresh=True) is True      # force-refresh recomputes


def test_frozen_rows_never_recompute():
    for st in ("overridden", "invoiced"):
        assert _ran(st, refresh=False) is False
        assert _ran(st, refresh=True) is False     # frozen even under refresh
