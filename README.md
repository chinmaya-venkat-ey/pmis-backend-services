# pmis-project-service

PMIS project-management microservice. Owns the M-A-T-S hierarchy
(projects → milestones → activities → tasks → subtasks), polymorphic
comments + attachments, the read paths for catalog tables (vendors,
resource_types, divisions, project_status_transitions), and the project
tree view.

Self-contained: JWT verification, RBAC, and the auth middleware all
live inside this service. Cross-service token verification works
because every PMIS service (monolith, user-service, this) uses HS256
with the same `SECRET_KEY` from environment.

Runs on port **8003**. Shares Postgres with the monolith and user-service.

## Quick start (Windows / PowerShell)

```powershell
cd path/to/pmis-project-service

# 1. Virtualenv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Dependencies
pip install -r requirements.txt

# 3. Env file
copy .env.example .env
# Edit .env — set SECRET_KEY to the SAME value the monolith and
# user-service use. Without this, token verification will fail.

# 4. Ensure Postgres is up (in WSL Ubuntu by default).

# 5. Boot
uvicorn app.main:app --reload --port 8003
```

Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/health
```

The response includes `secret_key_sha256_prefix` — compare against the
monolith's and user-service's same prefix to confirm all three share
the same signing key.

## Run via Docker (matches prod-style)

From WSL Ubuntu (or any Docker Engine host):

```bash
cd path/to/pmis-project-service
docker compose up --build
```

Stop any host uvicorn on port 8003 first — the container uses
`network_mode: host` and would conflict.

The Docker compose file mounts `/mnt/pmis_files` (the NFS attachment
path) — DevOps must mount the NFS export at that path on the host the
same way the monolith does.

## Architecture

```
Client / Postman
       │  Bearer <token minted by user-service>
       ▼
  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
  │ pmis-user-service│  │ pmis-backend     │  │ pmis-project-service │
  │      :8001       │  │      :8000       │  │       :8003          │
  │                  │  │                  │  │                      │
  │ Owns user/auth   │  │ (Strangler Fig — │  │ Owns project/M-A-T-S │
  │ writes; mints    │  │ duplicate of     │  │ writes; verifies     │
  │ JWTs.            │  │ all endpoints,   │  │ tokens locally via   │
  │                  │  │ being phased     │  │ shared SECRET_KEY.   │
  │                  │  │ out)             │  │                      │
  └────────┬─────────┘  └────────┬─────────┘  └──────────┬───────────┘
           │                     │                       │
           └────────────┬────────┴───────────────────────┘
                        ▼
              ┌─────────────────────────┐
              │     Shared Postgres     │
              │                         │
              │ user-service owns:      │
              │  - users                │
              │  - roles                │
              │  - revoked_tokens       │
              │                         │
              │ project-service owns:   │
              │  - projects             │
              │  - milestones           │
              │  - activities           │
              │  - tasks, subtasks      │
              │  - comments, attachments│
              │  - vendors, resource_   │
              │    types, divisions,    │
              │    project_status_      │
              │    transitions          │
              │                         │
              │ Monolith reads all of   │
              │ the above for now;     │
              │ writes get phased out.  │
              └─────────────────────────┘
```

**Coordination across services** happens through three shared things:

- **Shared Postgres** — one DB, one schema. Each service owns writes
  to its own tables; reads from any are visible to all.
- **Shared `SECRET_KEY`** — same value in every service's env. Tokens
  signed by user-service verify here using the same algorithm. No
  HTTP round-trip needed.
- **Shared blacklist (`revoked_tokens` table)** — logout writes a row
  in user-service; the auth middleware here reads it and rejects the
  token. Logout takes effect everywhere immediately.

## Endpoints

Phase 1 (this commit): only `/health`, `/`, and Swagger UI at `/docs`.
Module endpoints (`/api/v3/projects/*`, `/api/v3/milestones/*`, etc.)
get added per phase as modules port across.

## Layout

```
pmis-project-service/
├── Dockerfile
├── docker-compose.yml
├── alembic/                       # migrations (separate version table:
│                                    alembic_version_project_svc)
│   └── versions/
├── app/
│   ├── api/                       # routes, controllers, schemas
│   │   ├── router.py
│   │   └── v3/                    # populated per-module as ports happen
│   ├── core/
│   │   ├── config.py              # Settings (pydantic-settings)
│   │   ├── security.py            # JWT + password (self-contained)
│   │   ├── rbac.py                # Permission enum + ROLE_PERMISSIONS
│   │   ├── errors.py              # DomainError + HTTP mapping
│   │   ├── response.py            # HAL+JSON envelope (generic helpers)
│   │   ├── base_controller.py
│   │   ├── dependencies.py
│   │   └── middleware/
│   │       ├── auth.py            # JWT verify + blacklist check
│   │       ├── rbac.py            # require_authenticated, require_permission
│   │       └── logging.py
│   ├── domain/                    # populated per-module
│   ├── infrastructure/db/
│   │   ├── session.py
│   │   ├── models/                # populated per-module
│   │   └── repositories/          # populated per-module
│   ├── shared/                    # service_result, pagination, validators
│   └── main.py
├── tests/
│   ├── conftest.py                # in-memory SQLite + fixtures
│   └── test_*.py                  # populated per-module
├── alembic.ini
├── pytest.ini
├── requirements.txt
├── .env                           # gitignored — real SECRET_KEY here
├── .env.example
├── .dockerignore
├── .gitignore
└── MICROSERVICE_EXTRACTION.md     # (added once Phase 1 lands)
```

## Tests

```powershell
pytest
```

Phase 1: tests/ has only conftest.py — module test files are added per
phase as modules port. Expected at end of Phase 1: 0 tests, 0 failures.

## Alembic

This service uses a **separate version table**
(`alembic_version_project_svc`) so its migration chain does not collide
with the monolith's `alembic_version` or the user-service's
`alembic_version_user_svc` in the same database.

```powershell
python -m alembic revision --autogenerate -m "your message"
python -m alembic upgrade head
```

Each ported module appends its own idempotent `CREATE TABLE IF NOT
EXISTS` blocks to a follow-up migration. The shared Postgres already
has every project-management table from the monolith's chain, so on
the shared DB these migrations are no-ops; on a fresh DB they create
the schema this service owns.
