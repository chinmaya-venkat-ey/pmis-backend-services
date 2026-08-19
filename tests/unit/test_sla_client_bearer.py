"""SlaClient.trigger_activity_completion forwards the completing user's JWT as
the Authorization header when given, and omits it when absent (so contract-mgmt
degrades to the manual-observation email)."""
from __future__ import annotations

import httpx
import pytest

from app.services.sla_client import SlaClient


class _FakeResp:
    status_code = 200
    text = ""

    def json(self):
        return {"data": {"ok": True}}


class _FakeClient:
    captured: dict = {}

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None):
        _FakeClient.captured = {"url": url, "headers": headers or {}}
        return _FakeResp()


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    _FakeClient.captured = {}


def _client():
    c = SlaClient()
    c.base_url = "http://contract:8005"
    c.enabled = True
    return c


def test_forwards_authorization_header_when_bearer_given():
    _client().trigger_activity_completion("act-1", bearer_token="Bearer xyz.jwt")
    assert _FakeClient.captured["headers"].get("Authorization") == "Bearer xyz.jwt"
    assert "act-1/on-complete" in _FakeClient.captured["url"]


def test_omits_authorization_when_no_bearer():
    _client().trigger_activity_completion("act-1")
    assert "Authorization" not in _FakeClient.captured["headers"]
