# pmis-user-service

PMIS user-management and authentication microservice. Self-contained:
JWT signing/verification, password hashing (argon2id), RBAC, and the
auth middleware all live inside this service. Cross-service token
verification works because every PMIS service uses the same HS256
`SECRET_KEY` from environment.

Runs on port **8001**. Shares Postgres with the rest of PMIS.

## Quick start (Windows / PowerShell)

```powershell
cd C:\Users\WC544QK\Downloads\pmis-user-service

# 1. Virtualenv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Dependencies
pip install -r requirements.txt

# 3. Env file
copy .env.example .env
# Edit .env — set SECRET_KEY to the SAME value the monolith uses.

# 4. Ensure Postgres is up (in WSL Ubuntu by default).

# 5. Boot
uvicorn app.main:app --reload --port 8001
```

Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
```

## Run via Docker (matches prod-style)

From WSL Ubuntu (or any Docker Engine host):

```bash
cd /mnt/c/Users/WC544QK/Downloads/pmis-user-service
docker compose up --build
```

Stop any host uvicorn on port 8001 first — the container uses
`network_mode: host` and would conflict.

## Architecture

```
Client / Postman
       │  Bearer <token>
       ▼
   ┌──────────────────┐         ┌──────────────────┐
   │ pmis-user-service│         │ pmis-backend     │
   │      :8001       │         │      :8000       │
   │                  │         │                  │
   │ Signs + verifies │         │ Verifies tokens  │
   │ Owns user/auth   │         │ for its own      │
   │ writes           │         │ endpoints        │
   └────────┬─────────┘         └────────┬─────────┘
            │                            │
            └──────────┬─────────────────┘
                       ▼
            ┌─────────────────────┐
            │   Shared Postgres   │
            │                     │
            │ This service owns   │
            │ writes to:          │
            │  - users            │
            │  - roles            │
            │  - revoked_tokens   │
            └─────────────────────┘
```

**Coordination across services** happens through three shared things:

- **Shared Postgres** — one DB, one schema. This service owns writes
  to `users`, `roles`, `revoked_tokens`. The monolith reads them.
- **Shared `SECRET_KEY`** — same value in both services' env. Tokens
  signed here verify on the monolith using the same algorithm. No
  HTTP round-trip needed.
- **Shared blacklist (`revoked_tokens` table)** — logout writes a row
  here; any service's auth middleware reads the same row and rejects
  the token. Logout takes effect everywhere immediately.

## Endpoints

All under `/api/v3/users`:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/login` | public | Authenticate, receive access + refresh tokens |
| POST | `/introspect` | public | Token validation + refresh rotation |
| POST | `/logout` | authenticated | Hard logout (jti blacklist + refresh revoke) |
| GET | `/me` | authenticated | Current user |
| POST | `/create` | `USERS_CREATE` | Create user |
| GET | `` | `USERS_READ_ALL` | List users |
| GET | `/{id}` | `USERS_READ` | Get by id |
| PATCH | `/{id}` | `USERS_UPDATE` | Update user |
| PATCH | `/{id}/password` | `USERS_UPDATE` | Change password |
| DELETE | `/{id}` | `USERS_DELETE_ALL` | Delete user |

Plus `/health`, `/`, and Swagger UI at `/docs`.

## Layout

```
pmis-user-service/
├── Dockerfile
├── docker-compose.yml
├── alembic/                       # migrations (separate version table:
│                                    alembic_version_user_svc)
│   └── versions/
├── app/
│   ├── api/v3/users/              # routes, controller, schemas, services
│   ├── core/
│   │   ├── config.py              # Settings (pydantic-settings)
│   │   ├── security.py            # JWT + password (self-contained)
│   │   ├── rbac.py                # Permission enum + ROLE_PERMISSIONS
│   │   ├── errors.py              # DomainError + HTTP mapping
│   │   ├── response.py            # HAL+JSON envelope
│   │   ├── base_controller.py
│   │   ├── dependencies.py
│   │   └── middleware/
│   │       ├── auth.py            # JWT verify + blacklist check
│   │       ├── rbac.py            # require_authenticated, require_permission
│   │       └── logging.py
│   ├── domain/                    # User, Role dataclasses
│   ├── infrastructure/db/
│   │   ├── session.py
│   │   ├── models/                # UserModel, RoleModel, RevokedTokenModel
│   │   └── repositories/
│   ├── shared/                    # service_result, pagination, validators
│   └── main.py
├── tests/
│   ├── conftest.py                # in-memory SQLite + fixtures
│   └── test_users.py              # 35 tests
├── alembic.ini
├── pytest.ini
├── requirements.txt
├── .env                           # gitignored — real SECRET_KEY here
├── .env.example
├── .dockerignore
├── .gitignore
└── MICROSERVICE_EXTRACTION.md     # design + extraction history
```

## Tests

```powershell
pytest
```

Expected: 35 passed. Tests use in-memory SQLite via the conftest
fixture — no shared Postgres dependency.

## Alembic

This service uses a **separate version table**
(`alembic_version_user_svc`) so its migration chain does not collide
with the monolith's `alembic_version` in the same database.

```powershell
python -m alembic revision --autogenerate -m "your message"
python -m alembic upgrade head
```
