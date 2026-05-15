"""
capture_fixtures.py — Harvest request/response fixtures from the running monolith.

Used to seed `tests/parity/<svc>/<endpoint>/<scenario>.json` files used by parity tests
(PLAN.md §7.2). NOT part of any service's runtime.

Per Q28: the source-of-truth DB is read-only from prod; this script can run against
either the live monolith or a local Postgres seeded from a sanitized prod dump.

USAGE (skeleton — to be expanded in Phase 3):
    python tools/capture_fixtures.py \\
        --base-url http://localhost:8000 \\
        --admin-token "$ADMIN_JWT" \\
        --member-token "$PROJECT_MEMBER_JWT" \\
        --output-dir services/pmis-user-management/tests/parity/

CONTRACT:
- For each of the 64 FE-called endpoints (frontend.md inventory):
    1. Issue the canonical request (GET / POST etc.) with each role token.
    2. Save (request_method, request_url, request_body, request_headers,
       response_status, response_body, response_headers) as a JSON file
       under <output-dir>/<endpoint-slug>/<scenario>.json.
    3. Strip auth tokens before writing.

The current file is a SKELETON. Implementation in Phase 3 after the first
service ports (so the FE call list is concretely available).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture monolith fixtures for parity tests")
    parser.add_argument("--base-url", required=True, help="Monolith base URL (e.g. http://localhost:8000)")
    parser.add_argument("--admin-token", required=True, help="JWT for an admin user")
    parser.add_argument("--member-token", help="JWT for a project_member user (optional)")
    parser.add_argument("--output-dir", required=True, type=Path, help="Where to write fixtures")
    args = parser.parse_args()

    print(f"[stub] Would capture fixtures from {args.base_url} into {args.output_dir}", file=sys.stderr)
    print("[stub] Phase 3 implementation pending.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
