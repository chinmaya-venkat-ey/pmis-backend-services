#!/usr/bin/env python3
"""Replicate a source project's Manage-Teams assignments onto a target project.

Reads the SOURCE project's team-page (project owner/approver + per-activity
owner / ownerApprover / divisionUsers / divisionApprovers, all as user-ID arrays)
and writes the same onto the TARGET project, matching activities BY NAME (the
target's fresh activity IDs are looked up from its own team-page). `orgUser` is
sent empty so the user-management cross-service diff is skipped.

Stdlib only (urllib) — run with the harness container's python if the host has none:
    docker exec -i pmis-project python - <args...> < replicate-teams.py

Args (positional): USERS_BASE PROJECTS_BASE LOGIN PASSWORD OTP SOURCE_PID TARGET_PID
  e.g. remote: http://10.1.131.199/users http://10.1.131.199/projects superadmin '<pw>' 000000 <src> <tgt>
       local : http://localhost:8001    http://localhost:8003        superadmin DevAdmin123! 000000 <src> <tgt>
"""
import json, sys, urllib.request, urllib.error

U, P, LOGIN, PW, OTP, SRC, TGT = sys.argv[1:8]


def _req(method, url, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {method} {url}: {e.read()[:400]}")


def login():
    r = _req("POST", f"{U}/api/v3/users/login", body={"login": LOGIN, "password": PW})
    d = r["data"]
    if d.get("requires_otp"):
        eph = d["ephemeral_token"]
        try:
            _req("POST", f"{U}/api/v3/users/login/send-otp", body={"ephemeral_token": eph, "channel": "email"})
        except SystemExit:
            pass
        d = _req("POST", f"{U}/api/v3/users/login/verify-otp", body={"ephemeral_token": eph, "code": OTP})["data"]
    return d["access_token"]


PROJ = P
tok = login()
src = _req("GET", f"{PROJ}/api/v3/projects/{SRC}/team-page", tok)["data"]
tgt = _req("GET", f"{PROJ}/api/v3/projects/{TGT}/team-page", tok)["data"]

# index source activity assignments by (milestoneDisplayCode, displayCode) — a
# structural key that survives the activity/milestone being renamed (activity
# names differ between clones; display codes match by creation order).
def key(a):
    return (a.get("milestoneDisplayCode"), a.get("displayCode"))

src_by_key = {key(a): a for a in src.get("activities", [])}

activities_body = []
missing = []
for a in tgt.get("activities", []):
    s = src_by_key.get(key(a))
    if not s:
        missing.append(a["name"])
        continue
    # start from the FULL target activity (carries required displayCode/name/
    # milestoneId/ownerDivision/concernedDivisions + the target's own id) and
    # overlay the source project's owner/approver assignments.
    entry = dict(a)
    entry["owner"] = s.get("owner") or []
    entry["ownerApprover"] = s.get("ownerApprover") or []
    entry["divisionUsers"] = s.get("divisionUsers") or {}
    entry["divisionApprovers"] = s.get("divisionApprovers") or {}
    activities_body.append(entry)

body = {
    "orgUser": [],
    "projectOwner": src.get("projectOwner") or [],
    "activities": activities_body,
}

print(f"source activities: {len(src_by_key)} | target activities: {len(tgt.get('activities', []))} "
      f"| mapped: {len(activities_body)} | unmatched: {len(missing)}")
if missing:
    print("  UNMATCHED (no source by name):", missing[:8], "..." if len(missing) > 8 else "")

if "--dry-run" in sys.argv:
    print("DRY RUN — not writing. projectOwner:", json.dumps(body["projectOwner"], ensure_ascii=False)[:200])
else:
    _req("PUT", f"{PROJ}/api/v3/projects/{TGT}/team-page", tok, body)
    print(f"team-page PUT OK -> {TGT}")
