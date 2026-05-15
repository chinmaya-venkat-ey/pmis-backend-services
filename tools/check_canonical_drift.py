"""
check_canonical_drift.py — CI guard against drift between canonical and per-service copies.

Per PLAN.md §6.3, every duplicated file (core/security.py, core/rbac.py, core/response.py,
schemas/pagination.py) carries a "canonical: services/pmis-user-management/app/<path>"
header comment. This script:

  1. Finds every file with such a header across `services/`.
  2. Diffs each against its declared canonical.
  3. Fails (exit 1) on any difference not allowlisted in tools/canonical_allowlist.json.

USAGE:
    python tools/check_canonical_drift.py

ALLOWLIST FORMAT (tools/canonical_allowlist.json):
    {
      "services/pmis-project-management/app/core/security.py": [
        "lines 42-50 may differ — project-svc verifies but does not encode"
      ]
    }

This is a SKELETON. Implementation in Phase 3 once the canonical files exist.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    services_dir = repo_root / "services"
    if not services_dir.exists():
        print(f"[stub] services/ not found at {services_dir}", file=sys.stderr)
        return 0
    print("[stub] Drift check pending — Phase 3 implementation.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
