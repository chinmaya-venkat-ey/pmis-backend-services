# PMC project setup

Recreate the **"Project Management Consultants (PMC)"** project (the newer one —
live id `60c67666`) end-to-end against a PMIS backend, so you don't have to click
through project → milestones → activities → finance by hand every time.

## ▶ How to run it (create the project on the real server)

Run it **from your own machine with the EY VPN connected** — not on the server.
The container reaches `10.1.131.199` through your VPN, and there's nothing to copy
onto the server. Ports `80` and `8019` on the server must be reachable over the VPN.

```bash
cd /c/Programming/PMIS/scripts/pmc-setup
docker build -t pmis-pmc-setup .
docker run --rm pmis-pmc-setup --name "Project Management Consultants (PMC) - copy 2"
```

Each `docker run` creates a **fresh copy** end-to-end: project → 11 milestones →
activities (D9 = 4 quarterly + D10 = 20 quarterly resource activities, **D1–D3
marked completed**) → cost items → payment terms → publish, then **replicates the
team owners/approvers** from the source project. Default target is `--env remote`.

**Cost values.** By default resource costs come out as the **server computes them**
from the uploaded rate card (`COST_OVERRIDE=false`). To make the D9/D10 finance
match the resource-alignment sheet exactly, run with **`COST_OVERRIDE=true`** — the
container then overwrites each D9/D10 resource line's rate/cost to the sheet value
(this needs DB access; see below):

```bash
docker run --rm -e COST_OVERRIDE=true \
  pmis-pmc-setup --name "Project Management Consultants (PMC) - copy 3"
```

**Parameters** (env vars; flags after the image name go to `setup-pmc.sh`):

| env | default | meaning |
|---|---|---|
| `COST_OVERRIDE` | `false` | `false` = server/API-computed resource costs; `true` = overwrite D9/D10 costs to the sheet |
| `TEAM_SOURCE_PID` | PMC-copy `acabf366-…` | source project to copy owners/approvers from; `none` to skip |
| `PMIS_ENV` | `remote` | `remote` \| `local`; plus `PMIS_PROJECT_NAME`, `PMIS_USER_BASE`/`PMIS_PROJ_BASE`, `PMIS_LOGIN_USER`/`PASS`, `PMIS_OTP` |
| `DB_HOST` `DB_PORT` `DB_USER` `DB_PASS` `DB_NAME` | remote Postgres | only used when `COST_OVERRIDE=true` |

> `COST_OVERRIDE=true` writes rate/cost directly in the DB. If anyone later **edits
> a D9/D10 activity's resources**, the server re-snapshots and reverts the override
> for that activity — just re-run with `COST_OVERRIDE=true` (or apply the SQL).

(First run pulls the `python:3.12-slim` base; rebuilds are instant.)

**No Docker?** Run the script directly instead — same VPN requirement, but it also
needs the local harness up (it borrows the `pmis-project` container as a JSON
parser, since Windows has no `python3`):

```bash
cd /c/Programming/PMIS/scripts/pmc-setup
bash setup-pmc.sh --env remote --yes
```

---

```
./setup-pmc.sh [--env local|remote] [--name "..."] [--no-publish] [--dry-run] [--yes]
```

| flag | meaning |
|------|---------|
| `--env local`  | hit the local Docker harness (default) |
| `--env remote` | hit `10.1.131.199` (real server) — prompts for a `yes` confirmation first |
| `--name "..."` | name for the created project (default: `Project Management Consultants (PMC) (copy)`) |
| `--no-publish` | leave the project in draft (default publishes at the end) |
| `--dry-run`    | print a summary of what would be created; make no changes |
| `--fixture P`  | use a different fixture file |

Each run creates a **fresh** project (new UUID + project code); re-run as often as
you like. Examples:

```bash
./setup-pmc.sh --dry-run                       # sanity-check the fixture + login
./setup-pmc.sh --env local                     # full build on the harness
./setup-pmc.sh --env remote --name "PMC demo"  # build on the real server
```

## What it creates
vendors (`Ey India`, `UIDAI`) → project (+ description, dates, leave policy) →
**designation rate card** uploaded to leave-management for the new project id →
**11 milestones** (incl. the resource-based/partial ones `D9`, `D10`) →
**36 activities** (24 carry resource allocations, priced from the rate card) →
**5 cost items** (`fixed`, 2×`resource_cost`, `one_time`, `recurring_cost`, all at
**`taxPercent 18`** — tax auto-computes as 18 % of each line's cost) →
billing frequency → payment-term schedule (percent-of-payment + **LD-basis**:
phase-1 `D1–D4 = 8`, `D5 = 10`, `D6 = 8`, `D7 = 20`, `D8 = 30`; D9/D10 have no LD
basis, 100 % payment) → publish.

SLAs / contracts are intentionally **not** created.

## How it stays correct
- `pmc-fixture.json` is a curated snapshot of the live PMC, with everything
  referenced **by name** (vendors, divisions, milestones) so it is portable
  between environments. Values were captured from live; request **shapes** were
  verified against the current running services (validations change over time —
  this uses the current contract, not a stale copy).
- Environment-specific lookups are resolved at run time: vendors are
  resolve-or-create by name; **division** codes (project `owner`, activity
  `ownerDivision`/`concernedDivision`) are kept when the target knows them
  (e.g. `tmd-ii` on remote) and otherwise remapped to a valid local code
  (e.g. `civil` on the harness).

## Resource rates (important)
Resource allocations store `{designation, quantity, duration}`; the **monthly rate
and cost are snapshotted at write time** from the Java leave-management service for
the activity's contract year.
- On **remote**, the real service resolves all 11 PMC designations → real rates.
- On **local**, the harness uses a `mock` that only knows a few roles, so most
  allocations snapshot **rate 0** (expected — the mechanism still works; the finance
  roll-up is verifiable for the mock-known roles). The live PMC's own activities were
  blank, so the allocations here are **representative** (valid PMC roles); edit the
  `resources` arrays in the fixture if you want specific team compositions.

## Docker (for the devops repo)
A self-contained image bundles the script + fixture; `python3` in the image is the
JSON parser, so the container needs **nothing** but network access to the target
PMIS server.

```bash
docker build -t pmis-pmc-setup .
docker run --rm pmis-pmc-setup                       # create on remote (default), publish
docker run --rm pmis-pmc-setup --name "PMC demo" --no-publish
# supply creds/URLs at run time instead of the baked defaults:
docker run --rm -e PMIS_PROJ_BASE=http://host/projects -e PMIS_USER_BASE=http://host/users \
  -e PMIS_LOGIN_USER=superadmin -e PMIS_LOGIN_PASS='***' pmis-pmc-setup
```
The container must reach the PMIS server — `10.1.131.199` is on the EY VPN, so on a
Linux host use `--network host` (or ensure the Docker VM shares the VPN route).

## Resource rates (handled automatically)
Resource **monthly rates** aren't stored in PMIS — they live in the Java
leave-management service, keyed **per project id** (`GET/POST
:8019/api/designation-rates`). A copy has a *new* project id, so the script uploads
the bundled rate card **`pmc-designation-rates.xlsx`** for the new id (org `Ey India`)
**before** creating the activities — so each allocation snapshots the real rate at
write time, and the finance page shows real resource costs (~₹69.6M). This runs on
`--env remote` only; the local harness uses a built-in mock and the step is skipped.

`pmc-designation-rates.xlsx` is the 11 PMC designations × Year-1…7 rates (captured
from live). Edit it if the rates change; it must match the blank template from
`GET :8019/api/export/template/designation-rates` (header row, roles from row 2).

## Requirements (running the script directly, not via Docker)
- `bash` + `curl`.
- A JSON parser: `python3` if on `PATH`, otherwise the local Docker harness
  (container `pmis-project`) is used purely as a JSON engine — so on a Windows box
  with no host Python, keep the harness up even when targeting `--env remote`.

## D9 / D10 resource alignment (2026-08 — matches the resource-alignment sheet)
D9 (Transition, Phase 2) and D10 (In-life, Phase 3) staffing now come from the
resource-alignment sheet (19 roles; `pmc-designation-rates.xlsx`). Key points:

- **Rate card is keyed by CONTRACT YEAR (from the project start 2025-11-10) and is
  SHIFTED** so `Year-2` = the sheet's base rate (D9 lands in contract year 2),
  `Year-3..` escalate 5 %/yr (= sheet Phase-3 Year-2..Year-5). This is what makes the
  finance page reproduce the sheet given these specific dates — it is fragile if the
  project start or D9/D10 dates change, since the shift depends on which contract year
  each milestone falls in.
- **Per-year activities, quarterly resource lines.** The resource `duration` is capped
  at 3 (one quarter) and the rate is snapshotted once per *activity start date*. So D9
  is **1 activity** (start 2027-05-10 → contract year 2) and D10 is **4 activities**
  (starts 2028/29/30/31-05-10 → contract years 3–6), each carrying the year's quarterly
  lines (`quantity 1`, `duration` = that quarter's man-months). One activity → one
  contract year → one rate → no straddle across the Nov-10 contract-year boundary.
- **D10 no longer overlaps D9** — it runs 2028-05-10 → 2032-05-10 (4 funded years =
  sheet Phase-3 Y2–Y5). D9 stays 2027-05-10 → 2028-05-10.
- **D1–D3 activities** are flagged `markComplete` in the fixture; the script PATCHes them
  to `status=completed` after creation (cascades to the milestone roll-up).
- **Milestone names + dates** match the current remote PMC-copy.

**Verified on the LOCAL harness** (leave-mgmt mock carries the same 19 roles/shifted
rates — see `PMIS-project-management/app/clients/leave_designation_rates_client.py`
`_MOCK_RATE_CARDS`): finance page resource pre-tax **173,322,970**, tax (18 %)
**31,198,135**, total **204,521,105**; D9 46,848,000; D10 126,474,970 (30,643,200 /
32,175,360 / 33,784,128 / 29,872,282). Matches the sheet within ₹0.40 of rounding.
Backups: `pmc-fixture.json.bak`, `pmc-designation-rates.xlsx.bak`.
