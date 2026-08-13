"""The auto-provider seam inside SlaComplianceService._provider_value — the
opt-in gate, registry lookup, and fail-soft behaviour. Exercised without a real
DB by faking the session's metric-key query and the anchor lookup."""
from __future__ import annotations

from datetime import date

import pytest

from app.config import settings
from app.services.sla_compliance_service import SlaComplianceService
from app.services.sla_metric_providers import base as pbase
from app.services.sla_metric_providers.base import MetricProvider, ProviderContext


# ---- fakes ----------------------------------------------------------------

class _Result:
    def __init__(self, vals): self._vals = vals
    def scalars(self): return self
    def all(self): return self._vals


class _FakeDb:
    def __init__(self, metric_keys): self._metric_keys = metric_keys
    def execute(self, *a, **k): return _Result(self._metric_keys)


class _Obj:
    def __init__(self, **kw): self.__dict__.update(kw)


class _FakeProvider(MetricProvider):
    produces = frozenset({"__test_metric__"})
    def __init__(self, value=None, boom=False):
        self._value, self._boom = value, boom
    def provide(self, ctx: ProviderContext):
        if self._boom:
            raise RuntimeError("provider blew up")
        return self._value


@pytest.fixture
def registered():
    """Register a fake provider for '__test_metric__' and remove it after."""
    def _reg(prov):
        pbase._REGISTRY.append(prov)
        return prov
    added = []
    yield lambda p: (added.append(p), _reg(p))[1]
    for p in added:
        if p in pbase._REGISTRY:
            pbase._REGISTRY.remove(p)


def _svc(metric_keys):
    svc = SlaComplianceService.__new__(SlaComplianceService)  # bypass __init__/DB
    svc.db = _FakeDb(metric_keys)
    svc._anchor_for_activity = lambda _aid: date(2025, 1, 1)
    return svc


def _call(svc, bearer="jwt"):
    mapping = _Obj(id="m1", activity_id="a1")
    sla = _Obj(id="s1", sla_ref="ZZ-SLA007")
    return svc._provider_value(mapping, sla, {}, "p1", date(2026, 3, 1), bearer)


# ---- tests ----------------------------------------------------------------

def test_config_flag_defaults_off():
    assert settings.sla_auto_providers_enabled is False


def test_provider_skipped_when_flag_off(monkeypatch, registered):
    monkeypatch.setattr(settings, "sla_auto_providers_enabled", False)
    registered(_FakeProvider(value=42))
    assert _call(_svc(["__test_metric__"])) is None


def test_provider_fills_value_when_enabled(monkeypatch, registered):
    monkeypatch.setattr(settings, "sla_auto_providers_enabled", True)
    registered(_FakeProvider(value={"__test_metric__": 5}))
    assert _call(_svc(["__test_metric__"])) == {"__test_metric__": 5}


def test_provider_none_when_no_matching_provider(monkeypatch, registered):
    monkeypatch.setattr(settings, "sla_auto_providers_enabled", True)
    registered(_FakeProvider(value=42))              # produces __test_metric__
    assert _call(_svc(["some_other_metric"])) is None  # SLA has a different metric


def test_provider_returns_none_and_swallows_errors(monkeypatch, registered):
    monkeypatch.setattr(settings, "sla_auto_providers_enabled", True)
    registered(_FakeProvider(boom=True))
    assert _call(_svc(["__test_metric__"])) is None   # exception → None, no raise


def test_provider_none_value_falls_through(monkeypatch, registered):
    monkeypatch.setattr(settings, "sla_auto_providers_enabled", True)
    registered(_FakeProvider(value=None))
    assert _call(_svc(["__test_metric__"])) is None
