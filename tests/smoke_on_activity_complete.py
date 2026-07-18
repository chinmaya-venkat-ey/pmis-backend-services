"""Local smoke test — on_activity_complete against the live VM DB.

Runs the exact code path the deployed endpoint runs, but from THIS
checkout — no rebuild / redeploy needed. Every iteration:

    python tests/smoke_on_activity_complete.py

Points at the VM's live Postgres directly (10.1.131.199:5432,
credentials from CLAUDE memory), so the fix path is tested against
REAL data before the change is pushed. Notification client stays in
mock mode (no NOTIFICATION_SERVICE_URL set) so it just logs — the
test verifies the recipient-lookup + response shape, not the send.

Exit 0 if all assertions pass, non-zero on any failure.
"""
from __future__ import annotations

import os
import sys

# Make ``app.*`` importable when running from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://pmis_user:aadhaarpmis2026@10.1.131.199:5432/pmis_db",
)
# Reproduces the deployed VM misconfig — NOTIFICATION_CLIENT=real but
# NOTIFICATION_SERVICE_URL unset. The client should auto-downgrade to
# mock so we don't 500 on an unreachable dispatch. Verified by
# _assert_no_notif_dispatch_errors below.
os.environ.setdefault("NOTIFICATION_CLIENT", "real")
os.environ.setdefault("USER_MANAGEMENT_SERVICE_URL", "http://user-svc.test")

from app.db import SessionLocal  # noqa: E402
from app.services.sla_compliance_service import SlaComplianceService  # noqa: E402

# The PMC D8 activity used throughout the audit — has PMC-SLA001_,
# PMC-SLA002 (fixed_escalation, auto), and PMU-SLA004 (point_accumulation,
# manual) mapped to it.
ACTIVITY_ID = "79f0343b-de91-48cf-8a50-f80c7d409f52"


def _log(label, ok, detail=""):
    icon = "PASS" if ok else "FAIL"
    print(f"  [{icon}] {label}" + (f"  |  {detail}" if detail else ""))
    return ok


def main() -> int:
    print("=" * 76)
    print("Smoke test — on_activity_complete against LIVE VM DB")
    print("=" * 76)
    print(f"activity: {ACTIVITY_ID}")
    print()

    # Capture WARN/ERROR logs from the notifier so a "dispatch failed"
    # (real mode with no URL) is caught by the smoke test instead of
    # only surfacing in the deployed container's log.
    import logging
    _bad_logs: list = []
    class _CaptureHandler(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING and record.name.startswith(
                "app.clients.notification_client"
            ):
                # Fine to see the "forcing mock mode" downgrade — treat
                # only actual failures (dispatch failed / send failed) as
                # smoke-test failures.
                msg = record.getMessage()
                if "dispatch failed" in msg.lower() or "send failed" in msg.lower():
                    _bad_logs.append(msg)
    logging.getLogger().addHandler(_CaptureHandler())

    db = SessionLocal()
    try:
        service = SlaComplianceService(db)
        summary = service.on_activity_complete(ACTIVITY_ID)
    except Exception as exc:
        print(f"  [FATAL] {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 2
    finally:
        db.close()

    # ── Shape assertions ─────────────────────────────────────────────
    ok = True
    ok &= _log("returned a dict",
               isinstance(summary, dict),
               type(summary).__name__)
    ok &= _log("has activityId",
               summary.get("activityId") == ACTIVITY_ID,
               summary.get("activityId"))
    ok &= _log("has projectId (non-null)",
               bool(summary.get("projectId")),
               summary.get("projectId"))
    ok &= _log("evaluatedOn ISO string",
               isinstance(summary.get("evaluatedOn"), str),
               summary.get("evaluatedOn"))
    ok &= _log("totalMappings >= 1",
               summary.get("totalMappings", 0) >= 1,
               f"totalMappings={summary.get('totalMappings')}")

    auto = summary.get("autoEvaluated", [])
    manual = summary.get("manualNeeded", [])
    errors = summary.get("errors", [])

    ok &= _log("no errors on the pass",
               not errors,
               f"{errors}")

    # Per-entry shape
    for e in auto + manual:
        ok &= _log(f"entry '{e.get('sla_ref')}' has status",
                   bool(e.get("status")),
                   e.get("status"))

    print()
    print("=" * 76)
    print("Summary")
    print("=" * 76)
    print(f"  autoEvaluated:  {len(auto)}")
    for e in auto:
        print(f"     * {e.get('sla_ref')} [{e.get('formula_type')}] -> {e.get('status')}")
    print(f"  manualNeeded:   {len(manual)}")
    for e in manual:
        emails = e.get("notification_sent_to") or []
        print(f"     * {e.get('sla_ref')} [{e.get('formula_type')}] -> {e.get('status')}")
        print(f"       emails: {emails}")
    print(f"  errors:         {len(errors)}")

    ok &= _log(
        "no notifier dispatch/send failures",
        not _bad_logs,
        f"{len(_bad_logs)} failure lines"
        + (f": {_bad_logs[0][:120]}" if _bad_logs else ""),
    )

    if manual:
        # Manual entries should carry the notification_sent_to list.
        for e in manual:
            ok &= _log(
                f"manual entry '{e['sla_ref']}' has notification_sent_to key",
                "notification_sent_to" in e,
                f"keys={list(e.keys())}",
            )
        # At least one email should be found for the PMC project's D8
        # activity — the project has 2 project_owner rows plus an
        # activity_assignments owner row (verified via SQL earlier).
        any_emails = any((e.get("notification_sent_to") or []) for e in manual)
        ok &= _log(
            "at least one manualNeeded entry has emails",
            any_emails,
            "0 emails found — owner lookup broken" if not any_emails
            else f"emails: {[e.get('notification_sent_to') for e in manual]}",
        )

    print()
    if ok:
        print("ALL ASSERTIONS PASSED — safe to push")
        return 0
    else:
        print("ASSERTIONS FAILED — do not push yet")
        return 1


if __name__ == "__main__":
    sys.exit(main())