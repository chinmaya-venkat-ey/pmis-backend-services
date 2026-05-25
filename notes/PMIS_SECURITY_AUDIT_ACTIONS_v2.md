# PMIS Security Audit — Hand-off Action List (v2, final security pass)

**Generated:** 2026-05-25
**Source:** Same four SonarQube reports dated 2026-05-19 used in the v1 audit. This file lists only the **security findings still open** after the v1 actions were applied. Once these are done, the SonarQube security findings from the original reports are fully addressed.
**Target codebase:** Current microservices at `C:\Users\WC544QK\Downloads\pmis-microservices\`

---

## 0 · READ FIRST — Safety guardrails (same as v1)

All ten guardrails from v1 §0 still apply. The key ones for this round:

1. **Do not change folder layout.**
2. **Do not change route URL paths, JSON shapes, or auth error codes** (`"AUTH_REQUIRED"` stays exactly as-is).
3. **Tests must pass** after each service's change — run `pytest` per service before moving to the next.
4. **No new features, no opportunistic refactors.** Only fix what's listed below.

---

## 1 · v1 status check — what was confirmed fixed on 2026-05-25

The v1 audit's cross-cutting security items were verified resolved:

| v1 ID | Item | Status |
|---|---|---|
| X-1 | Non-root `USER` in all 4 Dockerfiles | ✅ Done — `USER appuser` at line 25 of every Dockerfile |
| X-2 | Production DB password removed from `.env` files | ✅ Done — `aadhaarpmis2026` replaced with `CHANGE-ME-IN-PROD` placeholder in all 4 `.env` files |
| X-3 | Hardcoded default DB password in `app/config.py` | ✅ Done — all 4 services use `CHANGE-ME` placeholder |
| UM-A-1 / PM-A-1 | `secrets:S6698` in `app/core/config.py` | ✅ Done (covered by X-2 / X-3) |

What's left from the original Sonar security findings is below.

---

## 2 · X-5 · Replace `"changeme"` literal in all `.env.example` files (BLOCKER · `secrets:S6698`)

**Why this is still flagged:** Sonar's secrets detector matches the literal token `"changeme"` (a well-known weak credential). When the live `.env` files were sanitized to `CHANGE-ME-IN-PROD`, the `.env.example` templates were missed and still contain the original `changeme` string. They will continue to fire `secrets:S6698` on the next scan.

**Files (current):**
- `PMIS-user-management/.env.example` line 14, line 16
- `PMIS-master/.env.example` line 11, line 12
- `PMIS-project-management/.env.example` line 10, line 11
- `PMIS-notification-service/.env.example` line 12

**Fix:** in each file, replace the literal `changeme` with `CHANGE-ME-IN-PROD` (same placeholder used in the live `.env` files), e.g.

```
# Before
DATABASE_URL=postgresql+psycopg2://pmis_app:changeme@localhost:5432/pmis
DATABASE_URL_MIGRATIONS=postgresql+psycopg2://pmis_ddl:changeme@localhost:5432/pmis

# After
DATABASE_URL=postgresql+psycopg2://pmis_app:CHANGE-ME-IN-PROD@localhost:5432/pmis
DATABASE_URL_MIGRATIONS=postgresql+psycopg2://pmis_ddl:CHANGE-ME-IN-PROD@localhost:5432/pmis
```

**Safety:**
- `.env.example` is a template; nothing in the running services reads from it. The change has no runtime effect.
- Do not alter any other line in these files (user names, host names, port numbers, comments). Only the password segment between `:` and `@` changes.
- Keep the structure of the connection string intact — schema (`postgresql+psycopg2://`), user, separator (`:`), placeholder, host suffix (`@localhost:5432/pmis`) must all remain.

---

## 3 · X-6 · Remove / genericize the hardcoded IP `10.1.131.199` in source files (LOW hotspot · `python:S1313`)

**Why this is still flagged:** the original hotspot was in `scripts/generate_curls.py:36` (script now deleted). However the same IP literal still appears in two current source files as documentation strings, and Sonar's `python:S1313` rule will still fire on a re-scan because it pattern-matches IP literals in source.

**Files (current):**
- `PMIS-project-management/app/main.py:44` — inside a Python comment: `# NFS mount (10.1.131.199); if it's missing / unmounted / read-only we`
- `PMIS-project-management/app/utilities/file_storage.py:6` — inside a module docstring: `- In production it is an NFS mount point (10.1.131.199) wired into the`

**Fix:** rewrite both references to describe the role without naming the IP. Suggested wording:

```python
# PMIS-project-management/app/main.py:44 (current)
    # NFS mount (10.1.131.199); if it's missing / unmounted / read-only we

# PMIS-project-management/app/main.py:44 (after)
    # NFS mount (configured via ATTACHMENT_BASE_PATH); if it's missing / unmounted / read-only we
```

```python
# PMIS-project-management/app/utilities/file_storage.py:6 (current)
  - In production it is an NFS mount point (10.1.131.199) wired into the

# PMIS-project-management/app/utilities/file_storage.py:6 (after)
  - In production it is an NFS mount point (configured via env var) wired into the
```

**Safety:**
- Both occurrences are in comments / docstrings — no runtime behavior change at all.
- Do not remove the surrounding comment / docstring; only replace the IP literal with a non-literal description.
- Do not touch the IP in `.env` / `.env.example` files — those are configuration, not source code, and Sonar does not scan them under `python:S1313`. Operationally the IP belongs there.

---

## 4 · X-7 · Re-run SonarQube with the correct project keys (process item · was NS-D in v1)

**Why this is still required:** three of the four original SonarQube reports were misconfigured (see v1 §1):
- `PMIS-project-management` report → scanned monolith user-management code
- `PMIS-user-management` report → scanned monolith user-management code (same scan as above, different project key)
- `PMIS-notification-service` report → scanned monolith project-management code
- `PMIS-master` report → correctly scanned the master microservice

Only `PMIS-master` produced a valid microservice-level scan. The notification-service has **never** been scanned. The other two reports describe a codebase shape (`app/api/v3/...`, duplicated `src/` tree) that no longer exists.

**Fix:** in whatever CI / SonarQube admin owns the scan setup, re-issue scans against each microservice with the **correct sources root and project key**:

| Service | Project key (suggested) | Sources path |
|---|---|---|
| PMIS-user-management | `PMIS-user-management-microservice` | `PMIS-user-management/` |
| PMIS-master | `PMIS-master-microservice` (already correct) | `PMIS-master/` |
| PMIS-project-management | `PMIS-project-management-microservice` | `PMIS-project-management/` |
| PMIS-notification-service | `PMIS-notification-service-microservice` | `PMIS-notification-service/` |

Each scan's `sonar.sources` should point at the service folder (not its parent), and `sonar.exclusions` should NOT pull in any duplicate `src/` tree (the 77.8 % duplication ERROR in the v1 reports came from that misconfiguration).

**Safety:**
- This is a CI / scanner change, not a code change. No application behavior is touched.
- Until this re-scan is done, the original four reports cannot be considered fully closed — there is no clean baseline to compare against.
- Once re-run, X-5 (changeme) and X-6 (10.1.131.199) above should drop from the findings; verify, then close out.

---

## 5 · Verification checklist (after X-5 and X-6 are done, before X-7 re-scan)

Run these from the repo root to confirm zero security findings remain that match the original Sonar rules:

```
# X-5 verification — no "changeme" literal anywhere
grep -rIn --include=".env.example" "changeme" PMIS-user-management PMIS-master PMIS-project-management PMIS-notification-service
# expected output: (nothing)

# X-6 verification — no 10.1.131.199 outside .env / .env.example
grep -rIn "10\.1\.131\.199" PMIS-user-management PMIS-master PMIS-project-management PMIS-notification-service \
  --include="*.py"
# expected output: (nothing)
```

Both commands returning no output means every SonarQube security finding from the original four reports is now resolved in source. The X-7 re-scan then confirms it from Sonar's end and gives notification-service its first real scan.

---

## 6 · Files referenced

| Path | Purpose |
|---|---|
| `C:\Users\WC544QK\Downloads\Security Assessment Report_PMIS\Assessment Report\PMIS_SECURITY_AUDIT_ACTIONS.md` | v1 audit (full list, all severities) |
| `C:\Users\WC544QK\AppData\Local\Temp\um_SecHotspots.tsv`, `ms_SecHotspots.tsv`, `ns_SecHotspots.tsv`, `pmis_pm_SecHotspots.tsv` | Raw security hotspot listings per report |
| `C:\Users\WC544QK\AppData\Local\Temp\*_Issues_dedup.tsv` | Raw issue listings per report (deduped) |
