#!/usr/bin/env bash
# =============================================================================
# setup-pmc.sh — recreate the "Project Management Consultants (PMC)" project
# (the newer one, live id 60c67666) end-to-end against a PMIS backend.
#
#   Creates: vendors -> project -> leave policy -> designation rate card (upload to
#            leave-mgmt, remote only) -> milestones -> activities (with resource
#            allocations, priced from the rate card) -> cost items ->
#            payment-term schedule -> (optional) publish.
#
# Data lives in  pmc-fixture.json  (next to this script) — a curated snapshot of
# the live PMC, with references by NAME so it is portable across environments.
# API request SHAPES were verified against the current services (validations
# change over time; this uses the current contract, not a stale copy).
#
# Usage:
#   ./setup-pmc.sh [--env local|remote] [--name "..."] [--no-publish]
#                  [--fixture PATH] [--dry-run] [--yes]
#
#   --env local    hit the local Docker harness (default)
#   --env remote   hit 10.1.131.199 (real server) — asks for confirmation
#   --name         name for the created project (default: fixture name + " (copy)")
#   --no-publish   leave the project in draft (default: publish at the end)
#   --dry-run      print what would be created, make no changes
#   --yes / -y     skip the remote confirmation prompt (non-interactive / container)
#
# Env overrides: PMIS_ENV, PMIS_PROJECT_NAME, PMIS_USER_BASE, PMIS_PROJ_BASE,
#                PMIS_LOGIN_USER, PMIS_LOGIN_PASS, PMIS_OTP.
# JSON is parsed with python3 if present, else the local Docker harness's python.
# =============================================================================
set -uo pipefail

# ----------------------------------------------------------------- args / config
ENVIRONMENT="${PMIS_ENV:-local}"
PROJECT_NAME="${PMIS_PROJECT_NAME:-}"
PUBLISH=1
DRY=0
ASSUME_YES=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE="$SCRIPT_DIR/pmc-fixture.json"

while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENVIRONMENT="$2"; shift 2;;
    --name) PROJECT_NAME="$2"; shift 2;;
    --no-publish) PUBLISH=0; shift;;
    --publish) PUBLISH=1; shift;;
    --fixture) FIXTURE="$2"; shift 2;;
    --dry-run) DRY=1; shift;;
    -y|--yes) ASSUME_YES=1; shift;;              # skip the remote confirmation (non-interactive / container)
    -h|--help) sed -n '2,32p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

case "$ENVIRONMENT" in
  local)
    USER_BASE="http://localhost:8001"
    PROJ_BASE="http://localhost:8003"
    LEAVE_BASE=""   # local harness runs leave-mgmt in "mock" mode — no rate-card upload
    LOGIN_USER="superadmin"; LOGIN_PASS="DevAdmin123!"; OTP="000000";;
  remote)
    USER_BASE="http://10.1.131.199/users"
    PROJ_BASE="http://10.1.131.199/projects"
    LEAVE_BASE="http://10.1.131.199:8019"   # Java leave-management (designation rates)
    LOGIN_USER="superadmin"; LOGIN_PASS="AuditPass!2026"; OTP="000000";;
  *) echo "--env must be local or remote" >&2; exit 2;;
esac

# Env-var overrides (let a container/CI supply creds + URLs instead of baking them in)
USER_BASE="${PMIS_USER_BASE:-$USER_BASE}"
PROJ_BASE="${PMIS_PROJ_BASE:-$PROJ_BASE}"
LEAVE_BASE="${PMIS_LEAVE_BASE:-$LEAVE_BASE}"
LOGIN_USER="${PMIS_LOGIN_USER:-$LOGIN_USER}"
LOGIN_PASS="${PMIS_LOGIN_PASS:-$LOGIN_PASS}"
OTP="${PMIS_OTP:-$OTP}"

# ----------------------------------------------------------------- helpers
c_grn=$'\033[32m'; c_red=$'\033[31m'; c_ylw=$'\033[33m'; c_dim=$'\033[2m'; c_rst=$'\033[0m'
log(){ echo "${c_dim}·${c_rst} $*"; }
ok(){  echo "${c_grn}✓${c_rst} $*"; }
warn(){ echo "${c_ylw}!${c_rst} $*" >&2; }
die(){ echo "${c_red}✗ $*${c_rst}" >&2; exit 1; }
hr(){ echo "${c_dim}────────────────────────────────────────────────────────${c_rst}"; }

[ -f "$FIXTURE" ] || die "fixture not found: $FIXTURE"

# --- pick a JSON-capable python -------------------------------------------------
# host python3 preferred; else use the harness container as a pure JSON engine.
PARSER=""; PY_CONTAINER="pmis-project"; FX="$FIXTURE"
_works(){ [ "$("$@" -c 'print(1)' 2>/dev/null)" = "1" ]; }   # actually run it (skip the Windows Store shim)
if   _works python3; then PARSER="host:python3"
elif _works python;  then PARSER="host:python"
elif [ "$(docker exec "$PY_CONTAINER" python -c 'print(1)' 2>/dev/null)" = "1" ]; then
  PARSER="docker"
  # stream the fixture in (avoids docker cp's colon-dest path getting mangled to C:\tmp on Git Bash)
  cat "$FIXTURE" | docker exec -i "$PY_CONTAINER" sh -c 'cat > /tmp/pmc-fixture.json' || die "could not stage fixture into $PY_CONTAINER"
  FX="//tmp/pmc-fixture.json"   # double slash: not mangled by Git Bash, collapses to /tmp in-container
else
  die "need a working python3/python, or the local Docker harness (container $PY_CONTAINER), for JSON parsing"
fi
export FX PROJECT_NAME       # visible to python (env passthrough on the docker parser)
log "JSON parser: $PARSER"

# py '<code>'  — runs python; forwards FX/VMAP/MMAP/VNAME/NAME from the caller's
# environment and pipes stdin through; prints to stdout.
py(){
  local code="$1"
  case "$PARSER" in
    host:python3) python3 -c "$code";;   # host python inherits the caller's env directly
    host:python)  python  -c "$code";;
    docker) docker exec -i -e FX -e VMAP -e MMAP -e VNAME -e NAME -e PROJECT_NAME -e DIVS -e DEFAULT_DIV "$PY_CONTAINER" python -c "$code";;
  esac
}

# curl wrapper — carries auth; prints body to stdout.
# Because callers capture the body with  x=$(req …)  (a subshell), the status code
# can't come back in a variable — it's written to $CODEFILE, read via  rc().
TOKEN=""   # set after login; empty is harmless on the login call itself
CODEFILE="$(mktemp)"; trap 'rm -f "$CODEFILE"' EXIT
rc(){ cat "$CODEFILE" 2>/dev/null; }   # HTTP status of the most recent req
req(){ # METHOD URL [JSON_BODY]
  local method="$1" url="$2" body="${3:-}" out
  if [ -n "$body" ]; then
    out=$(curl -s -m 30 -w $'\n%{http_code}' -X "$method" "$url" \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data "$body")
  else
    out=$(curl -s -m 30 -w $'\n%{http_code}' -X "$method" "$url" \
      -H "Authorization: Bearer $TOKEN")
  fi
  printf '%s' "${out##*$'\n'}" > "$CODEFILE"   # last line = status (survives the subshell via file)
  printf '%s' "${out%$'\n'*}"                  # everything before it = response body
}

# extract the entity UUID from a create response ("data.id")
extract_id(){ py 'import sys,json
d=json.load(sys.stdin); d=d.get("data",d)
print(d.get("id","") if isinstance(d,dict) else "")'; }

# ----------------------------------------------------------------- banner
hr
echo "PMIS · PMC project setup   env=${ENVIRONMENT}   base=${PROJ_BASE}"
hr
if [ "$ENVIRONMENT" = "remote" ] && [ "$DRY" = "0" ] && [ "$ASSUME_YES" = "0" ]; then
  warn "This will CREATE a project on the REMOTE server ($PROJ_BASE)."
  printf "Type 'yes' to continue (or pass --yes): "; read -r ans; [ "$ans" = "yes" ] || die "aborted"
fi

# ----------------------------------------------------------------- login
log "logging in as $LOGIN_USER …"
LR=$(req POST "$USER_BASE/api/v3/users/login" "{\"login\":\"$LOGIN_USER\",\"password\":\"$LOGIN_PASS\"}")
EPH=$(echo "$LR" | py 'import sys,json;d=json.load(sys.stdin);print(d.get("ephemeral_token") or d.get("data",{}).get("ephemeral_token") or "")')
TOKEN=$(echo "$LR" | py 'import sys,json;d=json.load(sys.stdin);print(d.get("access_token") or d.get("data",{}).get("access_token") or "")')
if [ -n "$EPH" ]; then
  VR=$(curl -s -m 20 -X POST "$USER_BASE/api/v3/users/login/verify-otp" -H 'Content-Type: application/json' \
        --data "{\"ephemeral_token\":\"$EPH\",\"code\":\"$OTP\"}")
  TOKEN=$(echo "$VR" | py 'import sys,json;d=json.load(sys.stdin);print(d.get("access_token") or d.get("data",{}).get("access_token") or "")')
fi
[ -n "$TOKEN" ] || die "login failed: $LR"
ok "authenticated"

if [ "$DRY" = "1" ]; then
  log "DRY RUN — summarising fixture, no writes:"
  echo "$(py 'import os,json
f=json.load(open(os.environ["FX"]))
print("  project     :", f["project"]["name"])
print("  vendors     :", ", ".join(v["name"] for v in f["vendors"]))
print("  milestones  :", len(f["milestones"]), "(resource-based:", ", ".join(m["name"].split(" - ")[0] for m in f["milestones"] if m["isResourceBased"]), ")")
acts=f["activitiesByMilestone"]; print("  activities  :", sum(len(v) for v in acts.values()), "( with resource allocations:", sum(1 for v in acts.values() for a in v if a["resources"]), ")")
print("  cost items  :", len(f["costItems"]))
print("  term overrides:", len(f["termOverrides"]))')"
  exit 0
fi

# ----------------------------------------------------------------- 0. valid divisions
# Division codes (owner / ownerDivision / concernedDivision) differ per environment
# (e.g. remote has tmd-i/tmd-ii; the local harness has civil/electrical). Keep the
# fixture value where the target knows it, else fall back to the first valid code.
DIVS=$(req GET "$PROJ_BASE/api/v3/divisions?pageSize=200" | py 'import sys,json
d=json.load(sys.stdin); els=d.get("data",{}).get("_embedded",{}).get("elements") or d.get("data") or []
print(json.dumps([x.get("code") for x in els if isinstance(x,dict) and x.get("code")]))')
[ -n "$DIVS" ] || DIVS="[]"
export DIVS
DEFAULT_DIV=$(echo "$DIVS" | py 'import sys,json;a=json.load(sys.stdin);print(a[0] if a else "")')
export DEFAULT_DIV
log "divisions in target: $DIVS (fallback: ${DEFAULT_DIV:-none})"

# ----------------------------------------------------------------- 1. vendors (resolve or create)
hr; log "resolving vendors …"
declare -A VEN
EXIST=$(req GET "$PROJ_BASE/api/v3/vendors?pageSize=200")
while IFS=$'\t' read -r vname; do
  [ -n "$vname" ] || continue
  vid=$(echo "$EXIST" | VNAME="$vname" py 'import os,sys,json
d=json.load(sys.stdin); els=d.get("data",{}).get("_embedded",{}).get("elements",[])
want=os.environ["VNAME"].strip().lower()
print(next((v["id"] for v in els if (v.get("name") or "").strip().lower()==want), ""))')
  if [ -z "$vid" ]; then
    body=$(VNAME="$vname" py 'import os,json;print(json.dumps({"name":os.environ["VNAME"],"phoneNumber":"0000000000","active":True}))' </dev/null)
    resp=$(req POST "$PROJ_BASE/api/v3/vendors/create" "$body")
    vid=$(echo "$resp" | extract_id)
    [ -n "$vid" ] || die "vendor create failed for '$vname' (HTTP $(rc)): $resp"
    ok "created vendor '$vname' → $vid"
  else
    ok "found vendor '$vname' → $vid"
  fi
  VEN["$vname"]="$vid"
done < <(py 'import os,json;[print(v["name"]) for v in json.load(open(os.environ["FX"]))["vendors"]]')

# vendor name->id map as JSON for downstream python
export VMAP=$(for k in "${!VEN[@]}"; do printf '%s\t%s\n' "$k" "${VEN[$k]}"; done | py 'import sys,json
m={}
for line in sys.stdin:
    line=line.rstrip("\n")
    if not line: continue
    k,v=line.split("\t",1); m[k]=v
print(json.dumps(m))')

# ----------------------------------------------------------------- 2. project
hr; log "creating project …"
[ -n "$PROJECT_NAME" ] || PROJECT_NAME="$(py 'import os,json;print(json.load(open(os.environ["FX"]))["project"]["name"]+" (copy)")')"
PBODY=$(NAME="$PROJECT_NAME" py 'import os,json
f=json.load(open(os.environ["FX"])); p=f["project"]; vmap=json.loads(os.environ["VMAP"])
divs=json.loads(os.environ.get("DIVS","[]")); dflt=os.environ.get("DEFAULT_DIV") or None
def dt(d,end=False): return None if not d else d+("T23:59:59+05:30" if end else "T00:00:00+05:30")
owner=p.get("owner")
if owner and owner not in divs: owner=dflt   # remap to a division the target knows
body={
  "name": os.environ["NAME"],
  "description": p.get("description") or "",
  "status": "new",
  "startDate": dt(p.get("startDate")),
  "endDate": dt(p.get("endDate"), True),
  "owner": owner,
  "taxPercent": p.get("taxPercent"),
  "ccnCapPercent": p.get("ccnCapPercent"),
  "totalProjectValueExclTax": p.get("totalProjectValueExclTax"),
  "vendorIds": [vmap[n] for n in p["vendorNames"] if n in vmap],
}
print(json.dumps({k:v for k,v in body.items() if v is not None}))')
PR=$(req POST "$PROJ_BASE/api/v3/projects/create" "$PBODY")
PID=$(echo "$PR" | extract_id)
[ -n "$PID" ] || die "project create failed (HTTP $(rc)): $PR"
ok "project '$PROJECT_NAME' → $PID"

# ----------------------------------------------------------------- 3. leave policy
LBODY=$(py 'import os,json
lc=json.load(open(os.environ["FX"]))["project"].get("leaveConfig") or {}
print(json.dumps(lc))')
if [ "$LBODY" != "{}" ]; then
  resp=$(req PUT "$PROJ_BASE/api/v3/projects/$PID/leave-policies" "$LBODY")
  [ "$(rc)" = "200" ] && ok "leave policy set" || warn "leave policy HTTP $(rc): $resp"
fi

# ----------------------------------------------------------------- 3b. designation rate card
# Resource monthly rates live in the Java leave-management service, keyed by project id.
# Register the rate sheet for THIS new project id BEFORE creating activities, so each
# resource allocation snapshots real rates at write time. Real leave-mgmt only (the
# local harness uses a built-in mock and ignores uploads).
RATE_SHEET="$SCRIPT_DIR/$(py 'import os,json;print(json.load(open(os.environ["FX"])).get("resourceRateSheet") or "")' </dev/null)"
RES_ORG_NAME="$(py 'import os,json;print(json.load(open(os.environ["FX"])).get("resourceOrg") or "")' </dev/null)"
if [ -z "$LEAVE_BASE" ]; then
  log "leave-management is mock/local — skipping rate-card upload (rates come from the mock)"
elif [ -n "$RES_ORG_NAME" ] && [ -f "$RATE_SHEET" ]; then
  hr; log "uploading designation rate card to leave-management …"
  ORG_ID="${VEN[$RES_ORG_NAME]:-}"
  PSTART="$(py 'import os,json;print(json.load(open(os.environ["FX"]))["project"].get("startDate") or "")' </dev/null)"
  PEND="$(py 'import os,json;print(json.load(open(os.environ["FX"]))["project"].get("endDate") or "")' </dev/null)"
  if [ -n "$ORG_ID" ]; then
    up=$(curl -s -m 60 -w '\n%{http_code}' -X POST \
      "$LEAVE_BASE/api/designation-rates/upload?projectId=$PID&organisationId=$ORG_ID&projectStartDate=$PSTART&projectEndDate=$PEND" \
      -H "Authorization: Bearer $TOKEN" -F "file=@$RATE_SHEET")
    case "$(echo "$up" | tail -1)" in
      200|201) ok "rate card uploaded for org '$RES_ORG_NAME' (resource rates will resolve)";;
      *) warn "rate-card upload HTTP $(echo "$up" | tail -1) — resource costs may snapshot 0: $(echo "$up" | sed '$d' | head -c 200)";;
    esac
  else
    warn "resource org '$RES_ORG_NAME' not resolved to an id — skipping rate-card upload"
  fi
else
  warn "rate sheet '$RATE_SHEET' missing — skipping upload (resource costs will snapshot 0)"
fi

# ----------------------------------------------------------------- 4. milestones
hr; log "creating milestones …"
declare -A MS
while IFS=$'\t' read -r mname mbody; do
  [ -n "$mname" ] || continue
  resp=$(req POST "$PROJ_BASE/api/v3/projects/$PID/milestones/create" "$mbody")
  mid=$(echo "$resp" | extract_id)
  [ -n "$mid" ] || die "milestone '$mname' failed (HTTP $(rc)): $resp"
  MS["$mname"]="$mid"
  ok "milestone ${mname%% - *} → $mid"
done < <(py 'import os,json
f=json.load(open(os.environ["FX"]))
def dt(d,end=False): return None if not d else d+("T23:59:59+05:30" if end else "T00:00:00+05:30")
for m in f["milestones"]:
    body={
      "name": m["name"], "description": m.get("description") or "",
      "startDate": dt(m.get("startDate")), "endDate": dt(m.get("endDate"), True),
      "isResourceBased": bool(m.get("isResourceBased")),
      "isTransactionBased": bool(m.get("isTransactionBased")),
      "category": m.get("category") or "original",
      "priority": m.get("priority"),
      "position": m.get("position"),
    }
    if m.get("paymentType"): body["paymentType"]=m["paymentType"]
    body={k:v for k,v in body.items() if v is not None}
    print(m["name"]+"\t"+json.dumps(body))')

# milestone name->id map
export MMAP=$(for k in "${!MS[@]}"; do printf '%s\t%s\n' "$k" "${MS[$k]}"; done | py 'import sys,json
m={}
for line in sys.stdin:
    line=line.rstrip("\n")
    if not line: continue
    k,v=line.split("\t",1); m[k]=v
print(json.dumps(m))')

# ----------------------------------------------------------------- 5. activities (+ resources)
hr; log "creating activities (with resource allocations) …"
acount=0; rcount=0; ccount=0
while IFS=$'\t' read -r mid abody hasres mark aend; do
  [ -n "$mid" ] || continue
  resp=$(req POST "$PROJ_BASE/api/v3/milestones/$mid/activities/create" "$abody")
  aid=$(echo "$resp" | extract_id)
  [ -n "$aid" ] || die "activity create failed (HTTP $(rc)): $resp"
  acount=$((acount+1)); [ "$hasres" = "1" ] && rcount=$((rcount+1))
  # markComplete (D1-D5 deliverables): flip status -> completed (cascades to the
  # milestone roll-up). Direct status set — bypasses the approval workflow.
  # Also stamp actualEndDate = planned endDate so LD/SLA has a real completion date to
  # derive on-time/late from — a completed activity/milestone with no actual end reads
  # as "no completion date" and yields no LD.
  if [ "$mark" = "1" ]; then
    cbody='{"status":"completed"}'
    [ -n "$aend" ] && cbody="{\"status\":\"completed\",\"actualEndDate\":\"$aend\"}"
    cresp=$(req PATCH "$PROJ_BASE/api/v3/activities/$aid" "$cbody")
    [ "$(rc)" = "200" ] && ccount=$((ccount+1)) || warn "mark-complete activity $aid HTTP $(rc): $cresp"
  fi
done < <(py 'import os,json
f=json.load(open(os.environ["FX"])); vmap=json.loads(os.environ["VMAP"]); mmap=json.loads(os.environ["MMAP"])
divs=json.loads(os.environ.get("DIVS","[]")); dflt=os.environ.get("DEFAULT_DIV") or None
def dt(d,end=False): return None if not d else d+("T23:59:59+05:30" if end else "T00:00:00+05:30")
for msname, acts in f["activitiesByMilestone"].items():
    mid=mmap.get(msname)
    if not mid: continue
    for a in acts:
        od=a.get("ownerDivision")
        if not od or od not in divs: od=dflt
        # concernedDivision is required: keep valid ones, else fall back to the default division
        cd=[x for x in (a.get("concernedDivision") or []) if x in divs] or ([dflt] if dflt else [])
        body={
          "name": a["name"], "description": a.get("description") or "",
          "startDate": dt(a.get("startDate")), "endDate": dt(a.get("endDate"), True),
          "category": a.get("category") or "original",
          "priority": a.get("priority"),
          "position": a.get("position"),
          "ownerDivision": od,
          "concernedDivision": cd,
        }
        if a.get("vendorName") and a["vendorName"] in vmap: body["vendorId"]=vmap[a["vendorName"]]
        if a.get("resources"): body["resources"]=[
            {"designation":r["designation"],"quantity":int(r["quantity"]),"duration":str(r["duration"])} for r in a["resources"]]
        body={k:v for k,v in body.items() if v is not None}
        print(mid+"\t"+json.dumps(body)+"\t"+("1" if a.get("resources") else "0")+"\t"+("1" if a.get("markComplete") else "0")+"\t"+(body.get("endDate") or ""))')
ok "activities created: $acount (with resource allocations: $rcount, marked completed: $ccount)"

# stamp actual end = planned end on each COMPLETED (markComplete) milestone. The milestone
# auto-completes via the activity roll-up; this only records its completion DATE so an LD/SLA
# evaluation can derive on-time/late (a completed milestone with no actual end reads as no-LD).
mecount=0
while IFS=$'\t' read -r msid msend; do
  [ -n "$msid" ] || continue
  meresp=$(req PATCH "$PROJ_BASE/api/v3/milestones/$msid" "{\"actualEndDate\":\"$msend\"}")
  [ "$(rc)" = "200" ] && mecount=$((mecount+1)) || warn "milestone actual-end $msid HTTP $(rc): $meresp"
done < <(py 'import os,json
f=json.load(open(os.environ["FX"])); mmap=json.loads(os.environ["MMAP"])
def dt(d,end=False): return None if not d else d+("T23:59:59+05:30" if end else "T00:00:00+05:30")
mc_names={ms for ms,acts in f["activitiesByMilestone"].items() if any(a.get("markComplete") for a in acts)}
end_by_name={m["name"]: dt(m.get("endDate"), True) for m in f["milestones"]}
for msname in sorted(mc_names):
    mid=mmap.get(msname); end=end_by_name.get(msname)
    if mid and end: print(mid+"\t"+end)')
ok "completed-milestone actual-end dates set: $mecount"

# ----------------------------------------------------------------- 6. cost items
hr; log "creating cost items …"
while IFS=$'\t' read -r label cbody; do
  [ -n "$cbody" ] || continue
  resp=$(req POST "$PROJ_BASE/api/v3/projects/$PID/cost-items" "$cbody")
  cid=$(echo "$resp" | extract_id)
  [ -n "$cid" ] || die "cost item '$label' failed (HTTP $(rc)): $resp"
  ok "cost item ${label} → $cid"
done < <(py 'import os,json
f=json.load(open(os.environ["FX"])); mmap=json.loads(os.environ["MMAP"])
for c in f["costItems"]:
    body={
      "costTypeCode": c["costTypeCode"],
      "phase": c.get("phase"),
      "cost": c.get("cost"),
      "taxPercent": c.get("taxPercent"),
      "perTransactionCost": c.get("perTransactionCost"),
      "plannedTransactions": c.get("plannedTransactions"),
      "lineLabel": c.get("lineLabel"),
      "frequencyCode": c.get("frequencyCode"),
      "milestoneIds": [mmap[n] for n in c.get("milestoneNames",[]) if n in mmap],
    }
    body={k:v for k,v in body.items() if v is not None}
    label="%s/phase-%s"%(c["costTypeCode"], c.get("phase"))
    print(label+"\t"+json.dumps(body))')

# ----------------------------------------------------------------- 7. project frequency
FREQ=$(py 'import os,json
f=json.load(open(os.environ["FX"]))
fq=next((t.get("frequencyCode") for t in f["termOverrides"] if t.get("frequencyCode")), None)
print(fq or "")')
if [ -n "$FREQ" ]; then
  resp=$(req PUT "$PROJ_BASE/api/v3/projects/$PID/frequency" "{\"frequencyCode\":\"$FREQ\"}")
  [ "$(rc)" = "200" ] && ok "billing frequency = $FREQ" || warn "frequency HTTP $(rc): $resp"
fi

# ----------------------------------------------------------------- 8. payment-term schedule
hr; log "applying payment-term schedule (pct / LD-basis) …"
TERMS=$(req GET "$PROJ_BASE/api/v3/projects/$PID/payment-terms?pageSize=500")
patched=0
while IFS=$'\t' read -r tid tbody; do
  [ -n "$tid" ] || continue
  resp=$(req PATCH "$PROJ_BASE/api/v3/payment-terms/$tid" "$tbody")
  [ "$(rc)" = "200" ] && patched=$((patched+1)) || warn "term $tid HTTP $(rc): $resp"
done < <(echo "$TERMS" | py 'import os,sys,json
f=json.load(open(os.environ["FX"])); mmap=json.loads(os.environ["MMAP"])
inv={v:k for k,v in mmap.items()}
resp=json.load(sys.stdin); terms=resp.get("data",{}).get("_embedded",{}).get("elements",[])
# index live terms by (phase, milestoneName)
idx={}
for t in terms:
    idx[(str(t.get("phase")), inv.get(t.get("milestoneId")))]=t["id"]
for ov in f["termOverrides"]:
    key=(str(ov.get("phase")), ov.get("milestoneName"))
    tid=idx.get(key)
    if not tid: continue
    patch={}
    if ov.get("percentOfPayment") is not None: patch["percentOfPayment"]=ov["percentOfPayment"]
    if ov.get("ldBasisPercent") is not None: patch["ldBasisPercent"]=ov["ldBasisPercent"]
    if not patch: continue
    print(tid+"\t"+json.dumps(patch))')
ok "payment terms patched: $patched"

# ----------------------------------------------------------------- 9. publish
if [ "$PUBLISH" = "1" ]; then
  hr; log "publishing project …"
  resp=$(req POST "$PROJ_BASE/api/v3/projects/$PID/publish" "{}")
  case "$(rc)" in
    200|201) ok "published";;
    *) warn "publish HTTP $(rc) (project left in draft): $resp";;
  esac
fi

hr
ok "DONE — project '$PROJECT_NAME'"
echo "   id:   $PID"
echo "   view: $PROJ_BASE/api/v3/projects/$PID/payment-page"
# Expose the created id + resolved bases/creds for a wrapping entrypoint
# (team replication + optional cost override run as follow-up steps).
if [ -n "$PMIS_PID_FILE" ]; then
  { echo "PID=$PID"; echo "USER_BASE=$USER_BASE"; echo "PROJ_BASE=$PROJ_BASE"
    echo "LOGIN_USER=$LOGIN_USER"; echo "LOGIN_PASS=$LOGIN_PASS"; echo "OTP=$OTP"
  } > "$PMIS_PID_FILE"
fi
hr
