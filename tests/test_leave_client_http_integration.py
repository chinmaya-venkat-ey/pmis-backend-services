"""Real-HTTP wiring check for the activity-availability client — the one thing
the pure-unit provider/PA tests can't cover: that LeaveManagementClient builds
the correct URL + query params and parses the real ActivityAvailabilityReport
JSON over an actual socket. Spins a throwaway HTTP server; no external deps."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.clients.leave_management_client import LeaveManagementClient

# One real ActivityAvailabilityReport (field names/types per leave-mgmt DEV DTO).
_REPORT = {
    "projectId": "p1", "activityId": "a1", "activityName": "Ops",
    "period": "07-Jan-2026 to 06-Apr-2026",
    "activityStartDate": "2026-01-07", "activityEndDate": "2026-04-06",
    "monthCount": 1,
    "months": [{
        "year": 2026, "month": 1, "period": "07-Jan-2026 to 06-Feb-2026",
        "fromDate": "2026-01-07", "toDate": "2026-02-06",
        "resourceCount": 2, "totalBusinessDays": 42,
        "totalPresentDays": 41.0, "totalWorkingHours": 352.0,
    }],
}

_CAPTURED: dict = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        _CAPTURED["path"] = self.path
        _CAPTURED["auth"] = self.headers.get("Authorization")
        body = json.dumps(_REPORT).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence
        pass


def test_client_hits_endpoint_and_parses_report():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client = LeaveManagementClient(base_url=f"http://127.0.0.1:{port}")
        got = client.get_activity_availability("p1", "a1", bearer_token="jwt-xyz")
    finally:
        srv.shutdown()

    # correct path + params + JWT forwarded
    assert _CAPTURED["path"].startswith("/api/attendance/report/availability/activity?")
    assert "projectId=p1" in _CAPTURED["path"]
    assert "activityId=a1" in _CAPTURED["path"]
    assert _CAPTURED["auth"] == "Bearer jwt-xyz"
    # parsed as an object with the month aggregates intact
    assert got["activityId"] == "a1"
    assert got["months"][0]["resourceCount"] == 2
    assert got["months"][0]["totalWorkingHours"] == 352.0
    assert got["months"][0]["totalBusinessDays"] == 42


def test_client_soft_fails_without_base_url_or_bearer():
    assert LeaveManagementClient(base_url="").get_activity_availability(
        "p1", "a1", bearer_token="jwt") is None
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # no bearer → client must not even call (returns None)
        assert LeaveManagementClient(base_url=f"http://127.0.0.1:{port}"
                                     ).get_activity_availability("p1", "a1") is None
    finally:
        srv.shutdown()
