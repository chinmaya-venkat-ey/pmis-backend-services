# PMIS Refactor — Plan (Checkpoint 3, revised)

Updated after your feedback on the first draft. References [AUDIT.md](C:/Programming/PMIS-refactor/AUDIT.md) for endpoint inventory and [REFACTOR_DECISIONS.md](C:/Programming/PMIS-refactor/REFACTOR_DECISIONS.md) for Phase 0 + Checkpoint 2 decisions. **No code under `services/`, `migrations/`, or `nginx/` is written until you say "proceed to implementation".**

---

## Preamble — your 11 feedback items addressed

1. **Folder structure clarity** → §1.2 now has a per-folder table: purpose, contains, does NOT contain. Distinguishes `db` vs `models` vs `repositories` etc.
2. **Nginx is reference only** → §3 reframed: nginx config is for devops's planning, not a build-time dependency. Services boot and run without it.
3. **Modern Pydantic v2 + SQLAlchemy 2.0** → new §2.1, §2.2. `Mapped[T]`/`mapped_column()`/`DeclarativeBase` for ORM; `BaseModel`/`ConfigDict`/`@field_validator` for schemas.
4. **Swagger doc quality + upload UX** → new §2.3 + §11.3. Every endpoint gets an OpenAPI `summary` + `description`; file params use `UploadFile = File(...)` so Swagger shows a "Choose files" button.
5. **Endpoint naming with verb suffixes** → new §2.4. `POST /user/users/create`, `DELETE /user/users/{id}/delete`, etc. Applied consistently. Same-path-different-method ambiguity gone.
6. **Masters RBAC** corrected → §9.6. Restored: `MASTER_DATA_VIEW` for reads, `MASTER_DATA_MANAGE` for writes. Dropped my earlier "auth-only tier" interpretation.
7. **Migration + deploy guides** → §11.1 + §11.2. Concrete deliverables in `docs/`.
8. **Schema name** → `users` instead of `user` (avoids the reserved-word issue). `users.users` is slightly redundant but unambiguous; no SQL quoting needed.
9. **Source-level drift warnings** → §2.5. Every file with a cross-schema mirror gets a header comment listing the mirror locations so a developer sees it before they break it.
10. **Granular Q26–Q35 answers** → §12 closes them out; no open questions blocking Phase 3.
11. **Service names prefixed `pmis-*`** → §1.1 docker-compose service names: `pmis-user-management`, `pmis-project-management`, `pmis-notification-management`, `pmis-masters-management`, `pmis-frontend`.

---

## §1 Target tree

### §1.1 Top-level layout

```
C:\Programming\PMIS-refactor\
├── README.md                          # links to docs/, decisions, how to run locally
├── .env.example                       # union of all service env vars
├── .gitignore
├── docker-compose.yml                 # ILLUSTRATIVE for devops; brings up all 6 containers locally
├── docker-compose.staging.yml         # disposable Postgres for migration validation
├── docker-compose.test.yml            # cross-service smoke + parity tests
│
├── nginx/                             # ILLUSTRATIVE config — devops decides production shape
│   ├── nginx.conf
│   └── conf.d/
│       ├── upstreams.conf
│       ├── proxy_headers.inc
│       └── pmis.conf
│
├── services/
│   ├── pmis-user-management/          # FastAPI app; container port 8001
│   ├── pmis-project-management/       # FastAPI app; container port 8003
│   ├── pmis-notification-management/  # FastAPI app; container port 8002
│   └── pmis-masters-management/       # FastAPI app; container port 8004 (NEW service)
│
├── migrations/                        # CROSS-SERVICE one-shot DB cutover scripts
│   ├── 00_create_schemas.sql
│   ├── 01_copy_data.sql
│   ├── 02_drop_legacy.sql             # post burn-in only
│   ├── 03_cleanup_permissions.sql     # legacy permission codes (Q25)
│   ├── 99_rollback.sql
│   └── README.md                      # runbook for operator
│
├── tools/
│   ├── capture_fixtures.py            # harvest request/response pairs from monolith
│   ├── check_canonical_drift.py       # diff per-service duplicates of canonical files
│   └── seed_bootstrap_users.py        # one-off used by alembic bootstrap migrations
│
└── docs/
    ├── MIGRATION_GUIDE.md             # § 11.1 — operator's how-to for the cutover
    ├── DEPLOY_GUIDE.md                # § 11.2 — illustrative; devops adapts
    ├── CUTOVER_RUNBOOK.md             # step-by-step for the maintenance window
    ├── OPENAPI_QUALITY.md             # § 11.3 — Swagger checklist Phase 3 enforces
    ├── BREAKING_CHANGES.md            # cumulative; mirrors § 9 here
    ├── MIGRATION_LOG.template.md      # per-service template; one filled in per service in Phase 3
    └── api_contracts/                 # generated OpenAPI specs post-port
```

Notes:
- **Docker-compose service names match the on-disk directory names** (`pmis-user-management`, etc.) per your Q35 answer.
- **The FastAPI URL prefix stays short** (`/user/*`, `/project/*`, `/notification/*`, `/masters/*`); the long name is the container/service identifier only.
- **Frontend repo path is unchanged** (`C:\Programming\PMIS\PMIS-Frontend-OpenProject`); the docker-compose service name is `pmis-frontend`. No code under it is modified.

### §1.2 Per-service folder anatomy

Every service uses this exact tree. Below: **what the folder is for, what goes in it, what does NOT.** This is the navigation map you wanted.

```
services/pmis-<svc>-management/
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── alembic/                  # see table below
│   ├── env.py
│   └── versions/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── models/
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   ├── controllers/
│   ├── routes/
│   ├── middleware/
│   ├── core/
│   └── utilities/
└── tests/
    ├── unit/
    ├── integration/
    ├── parity/
    └── conftest.py
```

| Folder / file | Purpose | Contains | Does NOT contain |
|---|---|---|---|
| **`alembic/`** | DB schema versioning. Each service owns a COMPLETE chain for its tables. | `env.py` (configures target_metadata + version_table='alembic_version_<svc>'); `versions/*.py` (migration scripts). | Application code; data fixtures (those live in `tools/`); no boot-time DDL (Q16). |
| **`app/main.py`** | Application entrypoint. | `FastAPI(...)` factory; lifespan handler (drop boot-time DDL per Q16); middleware order; router includes; exception handlers; root `/`, `/health`, `/ready` endpoints. | Business logic; per-resource routes (those go in `routes/`). |
| **`app/config.py`** | Configuration. | Pydantic `BaseSettings` subclass enumerating every env var; module-level `settings` singleton (`@lru_cache`). | Any code that *uses* settings — those live next to consumers. |
| **`app/db.py`** | DB plumbing. | `engine = create_engine(...)`; `SessionLocal = sessionmaker(...)`; `class Base(DeclarativeBase): pass`; `get_db()` dependency; soft-delete query helpers (`apply_soft_delete_filter`). | ORM model declarations (those go in `models/`); business queries (those go in `repositories/`); any commit logic (that's services'). |
| **`app/models/`** | SQLAlchemy 2.0 ORM models. One file per table. | `class User(Base): __tablename__='users'; __table_args__={'schema': 'users'}; id: Mapped[str] = mapped_column(...)`. Type-annotated columns. FK constraints (incl. cross-schema). Relationships when used. | Pydantic schemas (those are in `schemas/`); query logic (use `repositories/`); pure-Python dataclasses ("domain objects") — dropped per Q10. |
| **`app/models/_cross_schema.py`** | Read-only mirrors of foreign-service tables for JOINs (Q11 pattern). | SQLAlchemy classes pointing at another schema (e.g. `class Vendor(Base): __table_args__={'schema': 'masters'}; ...`). Header comment listing canonical location (§2.5). | Any write operation against the mirrored table (forbidden — owning service's responsibility). |
| **`app/schemas/`** | Pydantic v2 request/response shapes. One file per resource. | `BaseModel` classes; `model_config = ConfigDict(...)`; `Annotated[T, Field(...)]` field metadata; `@field_validator`/`@model_validator`; pagination envelopes (`Collection`); error envelopes (`ErrorEnvelope`). | Business rules (validators do INPUT validation only; semantic rules live in `services/`); SQLAlchemy models. |
| **`app/repositories/`** | Data access layer. One file per resource. | Class per resource (`UserRepository`); constructor takes `Session`; methods return SQLAlchemy model instances or scalars; encapsulates JOINs, filters, pagination math; uses `_cross_schema` models for cross-domain JOINs. | Business logic (e.g. "if user is admin then ..."); HTTP awareness; raw transaction commits (those happen at the request boundary via FastAPI session lifecycle, or explicitly in services for nested transactions). |
| **`app/services/`** | Business logic. One flat file per resource (`<resource>_service.py`) per Q9. | Classes/functions that orchestrate `repositories/`; enforce invariants (state-transition rules, RBAC checks beyond simple permission gates); cross-resource workflows; provider strategies (SMTP vs SendGrid vs MSG91 in notification-svc); transactional boundaries. | HTTP-aware code (controllers do that); raw SQL (use repositories); request validation (schemas do that). |
| **`app/controllers/`** | HTTP adapter layer. Kept per Q8. One file per resource. | Class per resource (`UserController`); constructor takes services; methods accept Pydantic request models and `Request` object; unpack to service args; call service; wrap result into Pydantic response model; map domain errors → `HTTPException`. | Business logic (services'); database queries (repositories'). |
| **`app/routes/`** | FastAPI route declarations. One file per resource. | `router = APIRouter(prefix='/users', tags=['users'])`; `@router.post(...)` decorators with OpenAPI `summary`+`description` (§2.3); FastAPI dependencies (`Depends(rbac.require_permission(USERS_CREATE))`, `Depends(get_controller)`, `Depends(get_db)`); only does: bind path params, validate body via Pydantic, inject deps, call controller, return response. | Logic beyond glue. |
| **`app/middleware/`** | Starlette/FastAPI middleware. | `auth_middleware.py` (JWT decode + revoked_token check + permission hydrate to `request.state`); `logging_middleware.py` (request_id, latency); `request_context.py` (correlation IDs). | Per-request route logic; exception handlers (those register in `main.py`). |
| **`app/core/`** | Cross-cutting framework primitives. | `security.py` (JWT encode/decode + argon2); `permissions.py` (permission code constants); `rbac.py` (`require_permission`, `require_authenticated`, `require_admin`, `require_project_permission`, `require_org_permission` factories); `errors.py` (`DomainError` hierarchy); `response.py` (HAL envelope formatters). **All of `core/` is framework-agnostic** — doesn't import from `app.models` or `app.repositories`. | Resource-specific code; DB queries beyond a `get_db()` shim. |
| **`app/utilities/`** | Small generic helpers. | `logger.py` (configure_logging, get_logger); datetime/timezone helpers; code generators (`generate_project_code`, `generate_user_code`); pagination math. | Resource-specific code; framework dependencies (those go in `core/`). |
| **`tests/unit/`** | Pure-function tests, no DB. | pytest test files. | Integration/DB tests. |
| **`tests/integration/`** | Route → controller → service → repo → real Postgres. | pytest tests using `TestClient` against a docker-compose Postgres; alembic migration + fixture setup in `conftest.py`. | Cross-service tests (those are in repo-root `tests/smoke/`). |
| **`tests/parity/`** | Wire-level diff against captured monolith fixtures (§7.2). | JSON request/response fixtures; pytest tests that re-issue the captured request and diff the response with tolerances. | Synthetic-data tests (those are integration). |
| **`tests/conftest.py`** | pytest fixtures shared by integration + parity. | `db_session`, `client`, `auth_headers`, seeded fixtures. | Production code. |

#### `core/` vs `utilities/` — the distinction

- **`core/`** = framework-dependent primitives (FastAPI deps, Starlette middleware-adjacent code, JWT, RBAC, errors). The "framework adapter" layer.
- **`utilities/`** = framework-agnostic helpers (logging config, date math, code generators). Could in principle move to any project.

#### `services/` vs `controllers/` — the distinction

- **`services/`** = "what the system does." `user_service.create(payload)` enforces uniqueness, hashes the password, persists, emits a notification. No HTTP awareness.
- **`controllers/`** = "how the system speaks HTTP." `UserController.create(request_model, current_user)` unpacks the Pydantic body, calls `user_service.create(...)`, handles `UserAlreadyExistsError` → 409, returns `UserResponse.model_validate(user)`. No business logic.

A controller that doesn't translate exceptions or shape responses is "thin glue." Per your Q8 explicitly, **we keep this layer even when thin** because it documents the HTTP boundary clearly and provides one place to put per-resource auth side-effects.

#### `repositories/` vs `services/` — the distinction

- **`repositories/`** = "what the data layer offers." `user_repo.get_active_by_login(login)` returns a `User` model or `None`. No business rules. Often returns lazy querysets or paginated tuples.
- **`services/`** = "what the business does with the data." `auth_service.authenticate(login, password)` calls `user_repo.get_active_by_login(login)`, verifies password, checks 2FA, mints tokens. Service composes repository calls + invariant checks.

### §1.3 notification-svc as the reference template

notification-svc is the simplest service (zero owned tables post-Q3 + Q13). Phase 3 starts there. Its filled-in tree is what the other three services mirror; deviations are explicit.

---

## §2 Code conventions

### §2.1 SQLAlchemy 2.0 patterns

Every ORM model uses the type-annotated 2.0 style. **No legacy `Column(...)` declarations without `Mapped[T]` annotation.**

```python
# services/pmis-user-management/app/models/user.py
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_login", "login", unique=True),
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_status", "status"),
        Index("ix_users_deleted_at", "deleted_at"),
        Index("ix_users_vendor_id", "vendor_id"),
        {"schema": "users"},                # this service owns the `users` schema
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_code: Mapped[Optional[str]] = mapped_column(String(16), unique=True)
    login: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(64))
    last_name: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")

    # Cross-schema FK: users.users.vendor_id → masters.vendors.id (Q1)
    vendor_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("masters.vendors.id", use_alter=True, name="fk_users_vendor"),
    )

    refresh_token_jti: Mapped[Optional[str]] = mapped_column(String(36))
    previous_refresh_token_jti: Mapped[Optional[str]] = mapped_column(String(36))
    previous_refresh_token_jti_valid_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.users.id"),     # self-FK
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
```

Conventions:
- `Mapped[T]` annotations on every column. `mapped_column(...)` instead of bare `Column(...)`.
- `Base = DeclarativeBase` in `app/db.py` (not the legacy `declarative_base()` factory).
- `__table_args__` is either a tuple (for indexes + kwargs) or a dict (just kwargs).
- Cross-schema FKs use `use_alter=True` to avoid circular dependency issues at CREATE time.
- Soft-delete pattern: `deleted_at` + `deleted_by` on resource tables; `active` boolean on static catalogs.

### §2.2 Pydantic v2 patterns

Schemas use the v2 API. **No legacy `class Config:` pattern; no `.dict()` / `.parse_obj()`.**

```python
# services/pmis-user-management/app/schemas/user.py
from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreateRequest(BaseModel):
    """Body of POST /user/users/create."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",                   # reject unknown fields
    )

    login: Annotated[
        str,
        Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$"),
    ]
    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=128)]
    first_name: Annotated[Optional[str], Field(default=None, max_length=64)]
    last_name: Annotated[Optional[str], Field(default=None, max_length=64)]
    vendor_id: Annotated[Optional[str], Field(default=None, pattern=r"^[0-9a-f-]{36}$")]

    @field_validator("login")
    @classmethod
    def login_lowercase(cls, v: str) -> str:
        return v.lower()


class UserResponse(BaseModel):
    """Response shape for /user/users/{id}/details and related."""

    model_config = ConfigDict(from_attributes=True)   # was orm_mode=True in v1

    id: str
    user_code: Optional[str] = None
    login: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: str
    vendor_id: Optional[str] = None
    two_factor_enabled: bool
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
```

Conventions:
- `model_config = ConfigDict(...)` replaces `class Config:`.
- `from_attributes=True` replaces `orm_mode=True` (enables `UserResponse.model_validate(orm_user)`).
- `Annotated[T, Field(...)]` for field metadata.
- `@field_validator("field_name")` replaces `@validator("field_name")`. Always paired with `@classmethod`.
- `@model_validator(mode="after")` for cross-field validation.
- Serialize/deserialize with `.model_dump()`, `.model_dump_json()`, `.model_validate()`, `.model_validate_json()`.
- `EmailStr` continues to come from `pydantic` (no extra package needed for that).

### §2.3 FastAPI patterns

**File uploads** use `UploadFile = File(...)` so Swagger renders a file picker (your point 4):

```python
# services/pmis-project-management/app/routes/attachment_routes.py
from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.controllers.attachment_controller import AttachmentController
from app.core.rbac import require_project_permission
from app.core.permissions import COMMENTS_CREATE
from app.dependencies import get_attachment_controller


router = APIRouter(prefix="/projects", tags=["attachments"])


@router.post(
    "/{project_uuid}/attachments/upload",
    summary="Upload attachments to a project",
    description=(
        "Attach one or more files to the project. Max 25 MB per file. "
        "Allowed extensions: pdf, docx, xlsx, txt, csv, jpg, jpeg, png, heic, mp4, webm, mov. "
        "Returns a HAL Collection of created attachment records."
    ),
    dependencies=[Depends(require_project_permission(COMMENTS_CREATE))],
)
async def upload_attachments(
    project_uuid: str,
    files: List[UploadFile] = File(
        ...,
        description="One or more files (max 25 MB each)",
    ),
    description: str = Form("", description="Optional shared caption for the batch"),
    controller: AttachmentController = Depends(get_attachment_controller),
):
    return await controller.upload(project_uuid, files, description)
```

**OpenAPI quality** (your point 4): every route decorator has `summary` (≤60 chars) and `description` (one-paragraph, explains what + when to call + what's returned). The `/docs` Swagger UI is the canonical API reference. Quality bar formalized in §11.3.

**Tags** group endpoints in Swagger by resource: `tags=["users"]`, `tags=["attachments"]`, `tags=["dashboard"]`, etc.

### §2.4 Endpoint naming — verb-suffix convention

Per your point 5, **same path with different HTTP methods is replaced with explicit verb suffixes.** No `POST /users` + `DELETE /users` ambiguity.

#### Rule

If a path's last segment is a **resource noun or path parameter**, append a verb suffix. If it's already an **action verb or action phrase**, leave it.

| Operation | URL pattern | Example |
|---|---|---|
| List collection | `…/<resource>/list` | `GET /user/users/list` |
| Create new | `…/<resource>/create` | `POST /user/users/create` |
| Get one by id | `…/<resource>/{id}/details` | `GET /user/users/{id}/details` |
| Update by id | `…/<resource>/{id}/update` | `PATCH /user/users/{id}/update` |
| Replace by id | `…/<resource>/{id}/replace` | `PUT /project/projects/{uuid}/replace` |
| Delete (soft) | `…/<resource>/{id}/delete` | `DELETE /user/users/{id}/delete` |
| Restore soft-deleted | `…/<resource>/{id}/restore` | `POST /user/users/{id}/restore` |
| Grant permission | `…/{id}/grant` | `POST /user/users/{id}/permissions/{code}/grant` |
| Revoke permission | `…/{id}/revoke` | `DELETE /user/users/{id}/permissions/{code}/revoke` |
| Domain action | `…/{id}/<verb>` (verb is the action) | `POST /project/projects/{uuid}/publish` |

#### Exceptions (verb-already-present)

These keep their current shape because the last segment is already a verb:
- `POST /user/users/login`, `/logout`, `/refresh`, `/introspect`, `/forgot-password`, `/reset-password`
- `POST /user/users/login/send-otp`, `/login/verify-otp`
- `GET /user/users/check-login`
- `POST /project/projects/{uuid}/save`, `/publish`, `/close`
- `GET /project/projects/{uuid}/tree`, `/discussion-feed`, `/audit-logs/list` (list of audit-logs — `/list` suffix)
- `GET /user/users/me/get` (me is a pronoun, so add `/get`)

#### Examples — user-svc

Old (`/api/v3/*`) → New (`/user/*` with verbs):

| Old | New |
|---|---|
| `POST /api/v3/users/login` | `POST /user/users/login` |
| `POST /api/v3/users/logout` | `POST /user/users/logout` |
| `POST /api/v3/users/refresh` | `POST /user/users/refresh` |
| `POST /api/v3/users/introspect` | `POST /user/users/introspect` |
| `GET  /api/v3/users/me` | `GET  /user/users/me/get` |
| `GET  /api/v3/users/me/permissions` | `GET  /user/users/me/permissions/list` |
| `POST /api/v3/users/login/send-otp` | `POST /user/users/login/send-otp` |
| `POST /api/v3/users/login/verify-otp` | `POST /user/users/login/verify-otp` |
| `POST /api/v3/users/forgot-password` | `POST /user/users/forgot-password` |
| `POST /api/v3/users/reset-password` | `POST /user/users/reset-password` |
| `POST /api/v3/users/create` | `POST /user/users/create` |
| `GET  /api/v3/users` | `GET  /user/users/list` |
| `GET  /api/v3/users/check-login` | `GET  /user/users/check-login` |
| `GET  /api/v3/users/{id}` | `GET  /user/users/{id}/details` |
| `PATCH /api/v3/users/{id}` | `PATCH /user/users/{id}/update` |
| `PATCH /api/v3/users/{id}/password` | `PATCH /user/users/{id}/password/update` |
| `DELETE /api/v3/users/{id}` | `DELETE /user/users/{id}/delete` |
| `POST /api/v3/users/{id}/restore` | `POST /user/users/{id}/restore` |
| `GET  /api/v3/users/{id}/permissions` | `GET  /user/users/{id}/permissions/list` |
| `POST /api/v3/users/{id}/permissions/{code}` | `POST /user/users/{id}/permissions/{code}/grant` |
| `DELETE /api/v3/users/{id}/permissions/{code}` | `DELETE /user/users/{id}/permissions/{code}/revoke` |
| `GET  /api/v3/users/{id}/role-assignments` | `GET  /user/users/{id}/role-assignments/list` |
| `POST /api/v3/users/{id}/role-assignments` | `POST /user/users/{id}/role-assignments/create` |
| `DELETE /api/v3/users/{id}/role-assignments/{aid}` | `DELETE /user/users/{id}/role-assignments/{aid}/delete` |
| `GET  /api/v3/users/{id}/projects` | `GET  /user/users/{id}/projects/list` |
| `GET  /api/v3/role-grants/{role_name}` | `GET  /user/role-grants/{role_name}/matrix` |
| `GET  /api/v3/master/roles` | `GET  /user/roles/list` |
| `POST /api/v3/master/roles/create` | `POST /user/roles/create` |
| `GET  /api/v3/master/roles/{id}` | `GET  /user/roles/{id}/details` |
| `PATCH /api/v3/master/roles/{id}` | `PATCH /user/roles/{id}/update` |
| `DELETE /api/v3/master/roles/{id}` | `DELETE /user/roles/{id}/delete` |
| `GET  /api/v3/master/roles/{id}/permissions` | `GET  /user/roles/{id}/permissions/list` |
| `PUT  /api/v3/master/roles/{id}/permissions` | `PUT  /user/roles/{id}/permissions/replace` |
| `POST /api/v3/master/roles/{id}/permissions/{code}` | `POST /user/roles/{id}/permissions/{code}/grant` |
| `DELETE /api/v3/master/roles/{id}/permissions/{code}` | `DELETE /user/roles/{id}/permissions/{code}/revoke` |
| `GET  /api/v3/master/permissions` | `GET  /user/permissions/list` |
| `GET  /api/v3/master/permissions/by-module` | `GET  /user/permissions/by-module/list` |
| `GET  /api/v3/master/permissions/{code}` | `GET  /user/permissions/{code}/details` |
| `POST /api/v3/master/permissions/create` | `POST /user/permissions/create` |
| `PATCH /api/v3/master/permissions/{code}` | `PATCH /user/permissions/{code}/update` |
| `DELETE /api/v3/master/permissions/{code}` | `DELETE /user/permissions/{code}/delete` |
| `GET  /api/v3/projects/{uuid}/role-assignments` | `GET  /user/projects/{uuid}/role-assignments/list` |
| `POST /api/v3/projects/{uuid}/role-assignments` | `POST /user/projects/{uuid}/role-assignments/create` |
| `DELETE /api/v3/projects/{uuid}/role-assignments/{aid}` | `DELETE /user/projects/{uuid}/role-assignments/{aid}/delete` |
| `GET  /api/v3/vendors/{vid}/projects` | `GET  /user/vendors/{vid}/projects/list` |
| `GET  /api/v3/vendors/{vid}/users` | `GET  /user/vendors/{vid}/users/list` |

#### Examples — project-svc

| Old | New |
|---|---|
| `POST /api/v3/projects/create` | `POST /project/projects/create` |
| `PUT  /api/v3/projects/{uuid}` | `PUT  /project/projects/{uuid}/replace` |
| `GET  /api/v3/projects` | `GET  /project/projects/list` |
| `GET  /api/v3/projects/all` | `GET  /project/projects/all/list` |
| `GET  /api/v3/projects/{uuid}` | `GET  /project/projects/{uuid}/details` |
| `PATCH /api/v3/projects/{uuid}` | `PATCH /project/projects/{uuid}/update` |
| `DELETE /api/v3/projects/{uuid}` | `DELETE /project/projects/{uuid}/delete` |
| `POST /api/v3/projects/{uuid}/save` | `POST /project/projects/{uuid}/save` |
| `POST /api/v3/projects/{uuid}/publish` | `POST /project/projects/{uuid}/publish` |
| `POST /api/v3/projects/{uuid}/close` | `POST /project/projects/{uuid}/close` |
| `GET  /api/v3/projects/{uuid}/tree` | `GET  /project/projects/{uuid}/tree` |
| `GET  /api/v3/projects/{uuid}/assignable-users` | `GET  /project/projects/{uuid}/assignable-users/list` |
| `GET  /api/v3/projects/{uuid}/audit-logs` | `GET  /project/projects/{uuid}/audit-logs/list` |
| `GET  /api/v3/projects/{uuid}/attachments` | `GET  /project/projects/{uuid}/attachments/list` |
| `POST /api/v3/projects/{uuid}/attachments` | `POST /project/projects/{uuid}/attachments/upload` |
| `GET  /api/v3/projects/{uuid}/discussion-feed` | `GET  /project/projects/{uuid}/discussion-feed` |
| `POST /api/v3/projects/{uuid}/milestones/create` | `POST /project/projects/{uuid}/milestones/create` |
| `GET  /api/v3/projects/{uuid}/milestones` | `GET  /project/projects/{uuid}/milestones/list` |
| `GET  /api/v3/milestones/{id}` | `GET  /project/milestones/{id}/details` |
| `PATCH /api/v3/milestones/{id}` | `PATCH /project/milestones/{id}/update` |
| `DELETE /api/v3/milestones/{id}` | `DELETE /project/milestones/{id}/delete` |
| `POST /api/v3/milestones/{id}/restore` | `POST /project/milestones/{id}/restore` |
| `POST /api/v3/milestones/{id}/activities/create` | `POST /project/milestones/{id}/activities/create` |
| `GET  /api/v3/milestones/{id}/activities` | `GET  /project/milestones/{id}/activities/list` |
| `GET  /api/v3/activities/{id}` | `GET  /project/activities/{id}/details` |
| `PATCH /api/v3/activities/{id}` | `PATCH /project/activities/{id}/update` |
| `DELETE /api/v3/activities/{id}` | `DELETE /project/activities/{id}/delete` |
| `POST /api/v3/activities/{id}/restore` | `POST /project/activities/{id}/restore` |
| `POST /api/v3/activities/{id}/tasks/create` | `POST /project/activities/{id}/tasks/create` |
| `GET  /api/v3/activities/{id}/tasks` | `GET  /project/activities/{id}/tasks/list` |
| `GET  /api/v3/tasks/{id}` | `GET  /project/tasks/{id}/details` |
| `PATCH /api/v3/tasks/{id}` | `PATCH /project/tasks/{id}/update` |
| `DELETE /api/v3/tasks/{id}` | `DELETE /project/tasks/{id}/delete` |
| `POST /api/v3/tasks/{id}/restore` | `POST /project/tasks/{id}/restore` |
| `POST /api/v3/tasks/{id}/subtasks/create` | `POST /project/tasks/{id}/subtasks/create` |
| `GET  /api/v3/tasks/{id}/subtasks` | `GET  /project/tasks/{id}/subtasks/list` |
| `POST /api/v3/subtasks/{pid}/subtasks/create` | `POST /project/subtasks/{pid}/subtasks/create` |
| `GET  /api/v3/subtasks/{id}` | `GET  /project/subtasks/{id}/details` |
| `GET  /api/v3/subtasks/{id}/subtasks` | `GET  /project/subtasks/{id}/subtasks/list` |
| `PATCH /api/v3/subtasks/{id}` | `PATCH /project/subtasks/{id}/update` |
| `DELETE /api/v3/subtasks/{id}` | `DELETE /project/subtasks/{id}/delete` |
| `POST /api/v3/subtasks/{id}/restore` | `POST /project/subtasks/{id}/restore` |
| `POST /api/v3/{kind}/{id}/comments` (×4) | `POST /project/{kind}/{id}/comments/create` (×4) |
| `GET  /api/v3/{kind}/{id}/comments` (×4) | `GET  /project/{kind}/{id}/comments/list` (×4) |
| `DELETE /api/v3/comments/{id}` | `DELETE /project/comments/{id}/delete` |
| `POST /api/v3/{kind}/{id}/attachments` (×4) | `POST /project/{kind}/{id}/attachments/upload` (×4) |
| `GET  /api/v3/{kind}/{id}/attachments` (×4) | `GET  /project/{kind}/{id}/attachments/list` (×4) |
| `DELETE /api/v3/attachments/{id}` | `DELETE /project/attachments/{id}/delete` |
| `GET  /api/v3/dashboard/summary` | `GET  /project/dashboard/summary` |
| `GET  /api/v3/dashboard/projects` | `GET  /project/dashboard/projects/list` |
| `GET  /api/v3/dashboard/projects/{uuid}` | `GET  /project/dashboard/projects/{uuid}/details` |
| `GET  /api/v3/dashboard/projects/{uuid}/items` | `GET  /project/dashboard/projects/{uuid}/items/list` |
| `GET  /api/v3/dashboard/organisations` | `GET  /project/dashboard/organisations/list` |
| `GET  /api/v3/dashboard/organisations/{vid}` | `GET  /project/dashboard/organisations/{vid}/details` |

#### Examples — masters-svc

| Old | New |
|---|---|
| `GET  /api/v3/master/divisions` | `GET  /masters/divisions/list` |
| `POST /api/v3/master/divisions/create` | `POST /masters/divisions/create` |
| `PATCH /api/v3/master/divisions/{code}` | `PATCH /masters/divisions/{code}/update` |
| `DELETE /api/v3/master/divisions/{code}` | `DELETE /masters/divisions/{code}/delete` |
| `POST /api/v3/master/divisions/{code}/restore` | `POST /masters/divisions/{code}/restore` |
| `GET  /api/v3/master/vendors` | `GET  /masters/vendors/list` |
| `GET  /api/v3/master/vendors/{vid}` | `GET  /masters/vendors/{vid}/details` |
| `POST /api/v3/master/vendors/create` | `POST /masters/vendors/create` |
| `PATCH /api/v3/master/vendors/{vid}` | `PATCH /masters/vendors/{vid}/update` |
| `DELETE /api/v3/master/vendors/{vid}` | `DELETE /masters/vendors/{vid}/delete` |
| `POST /api/v3/master/vendors/{vid}/restore` | `POST /masters/vendors/{vid}/restore` |
| `GET  /api/v3/master/vendors/{vid}/projects` | `GET  /masters/vendors/{vid}/projects/list` |
| ... | ... |
| `GET  /api/v3/master/notification_templates` | `GET  /masters/notification-templates/list` |
| `POST /api/v3/master/notification_templates/create` | `POST /masters/notification-templates/create` |
| `PATCH /api/v3/master/notification_templates/{id}` | `PATCH /masters/notification-templates/{id}/update` |
| `DELETE /api/v3/master/notification_templates/{id}` | `DELETE /masters/notification-templates/{id}/delete` |
| `POST /api/v3/master/notification_templates/{id}/restore` | `POST /masters/notification-templates/{id}/restore` |

(All other catalogs — `resource_types`, `project_categories`, `activity_types`, `activity_statuses`, `milestone_statuses`, `project_status_transitions`, `priorities` — follow the same pattern.)

#### Examples — notification-svc

| Old | New |
|---|---|
| `POST /api/v1/notifications/email/send` | `POST /notification/email/send` |
| `POST /api/v1/notifications/sms/send` | `POST /notification/sms/send` |
| `POST /api/v1/notifications/otp/send` | `POST /notification/otp/send` |
| `POST /api/v1/notifications/otp/verify` | `POST /notification/otp/verify` |
| `POST /api/v1/notifications/dispatch` | `POST /notification/dispatch` |
| `POST /api/v1/notifications/cron/daily-digest` | `POST /notification/cron/daily-digest` |

(All last-segments are already verbs/action-phrases — no suffix added.)

### §2.5 Cross-schema mirror warning headers

Per your point 9, every file with a cross-service implication gets a header comment so a developer sees it before they break a cross-service consumer.

**On the canonical model (in user-svc):**
```python
# services/pmis-user-management/app/models/role_permission.py
"""
WARNING: This model's column layout is MIRRORED in:
  - services/pmis-project-management/app/models/_cross_schema.py (class RolePermission)
  - services/pmis-notification-management/app/models/_cross_schema.py (class RolePermission)
  - services/pmis-masters-management/app/models/_cross_schema.py (class RolePermission)

Any column rename, type change, or constraint change here MUST be replicated
in each mirror, OR the mirrors must be updated to match.

CI catches drift via tests/test_cross_schema_drift.py (run on every PR in user-svc).
"""
```

**On each mirror:**
```python
# services/pmis-project-management/app/models/_cross_schema.py
"""
READ-ONLY mirror declarations. These tables are OWNED by other services:
  - users.users, users.roles, users.permissions, users.user_roles,
    users.user_role_assignments, users.role_permissions, users.user_permissions,
    users.revoked_tokens
        → owned by pmis-user-management
  - masters.vendors, masters.divisions, masters.resource_types, masters.priorities,
    masters.notification_templates, masters.project_categories,
    masters.activity_types, masters.activity_statuses, masters.milestone_statuses,
    masters.project_status_transitions
        → owned by pmis-masters-management

This service NEVER writes to these tables. The mirrors exist only for
read-only JOIN queries (auth permission hydration, FK target validation,
cross-domain response embedding).

If you need to change a column here, the change MUST originate in the owning
service (see the canonical model file referenced in each class's docstring).
CI test (drift check) will fail if these mirrors diverge from the owning service's
declarations.
"""
```

### §2.6 Logging, errors, response envelopes

- **Logging**: stdlib `logging` configured by `utilities/logger.py`. JSON output in prod (`ENV=production`), human-readable in dev. Per-request `request_id` from `middleware/request_context.py`.
- **Errors**: `DomainError` hierarchy in `core/errors.py` (subclasses for `NotFound`, `Conflict`, `Forbidden`, `ValidationError`). Mapped to HTTP status codes by a single `@app.exception_handler(DomainError)` in `main.py`. No raw `HTTPException` in services — services raise `DomainError` subclasses; controllers may translate if needed.
- **Response envelope**: HAL Collection `{"_type": "Collection", "_embedded": {"elements": [...]}, "total": N, "count": M, "pageSize": P, "offset": O, "_links": {...}}` for lists. Single resources: bare object or HAL `{"_type": "User", "_links": {...}, ...attributes}`. Error envelope: `{"code": "USER_NOT_FOUND", "message": "User does not exist", "details": {...}}`.

---

## §3 Nginx — illustrative only

**Per your point 2: nginx is NOT a hard dependency of the new app.**

- Each service is independently runnable via `docker run pmis-user-management` or `uvicorn app.main:app --port 8001`. It binds requests at its own URL prefix (`/user/*` etc) regardless of what fronts it.
- The `nginx/` directory in this repo is a **reference config for devops to read, criticize, and adapt**. It is not invoked by service tests; it is included in `docker-compose.yml` only as a convenience for local end-to-end testing.
- Production deployment of nginx (or any other reverse proxy) is **devops's decision**. They may use Traefik, an LB, etc. The services do not know or care which one is in front.

### Illustrative config (for devops's reference)

```nginx
# nginx/conf.d/upstreams.conf  -- ILLUSTRATIVE
upstream pmis_user          { server pmis-user-management:8001; }
upstream pmis_project       { server pmis-project-management:8003; }
upstream pmis_notification  { server pmis-notification-management:8002; }
upstream pmis_masters       { server pmis-masters-management:8004; }
upstream pmis_frontend      { server pmis-frontend:3000; }

# nginx/conf.d/pmis.conf  -- ILLUSTRATIVE
server {
    listen 80;
    server_name _;
    client_max_body_size 25m;     # matches MAX_UPLOAD_MB=25 (Q22)
    proxy_connect_timeout 5s;
    proxy_read_timeout 60s;
    proxy_send_timeout 60s;

    location /user/         { proxy_pass http://pmis_user;         include conf.d/proxy_headers.inc; }
    location /project/      { proxy_pass http://pmis_project;      include conf.d/proxy_headers.inc; }
    location /notification/ { proxy_pass http://pmis_notification; include conf.d/proxy_headers.inc; }
    location /masters/      { proxy_pass http://pmis_masters;      include conf.d/proxy_headers.inc; }

    # Health-check passthroughs (devops adapts to their probe framework)
    location = /health/user         { proxy_pass http://pmis_user/health; }
    location = /health/project      { proxy_pass http://pmis_project/health; }
    location = /health/notification { proxy_pass http://pmis_notification/health; }
    location = /health/masters      { proxy_pass http://pmis_masters/health; }
    location = /ready/user          { proxy_pass http://pmis_user/ready; }
    location = /ready/project       { proxy_pass http://pmis_project/ready; }
    location = /ready/notification  { proxy_pass http://pmis_notification/ready; }
    location = /ready/masters       { proxy_pass http://pmis_masters/ready; }

    location / { proxy_pass http://pmis_frontend; }

    # CORS owned by nginx in prod (per Decision 8e); services skip CORSMiddleware unless ENV=development
}
```

**Code-side implications** (the only things services bake in):
- `ROOT_PATH` env var per service (default `""`). Lets devops put the whole app under a corporate prefix without code change.
- `/health` and `/ready` endpoints at app root, outside the service prefix.
- `CORSMiddleware` registered only when `ENV=development`.
- Upload handlers enforce `MAX_UPLOAD_MB=25` in code (so a misconfigured nginx doesn't let oversize bodies in).

---

## §4 Migration order with dependency diagram

**Order (per Q19 + Q29 confirmed):**

1. **pmis-notification-management** — zero owned tables post-Q3+Q13; pure dispatcher
2. **pmis-masters-management** — catalogs + reference data; NEW service
3. **pmis-user-management** — auth domain; everyone reads from it
4. **pmis-project-management** — biggest schema; reads from `users` and `masters`

**Dependency diagram** (▲ = "reads cross-schema from"):

```
            ┌────────────────────────┐
            │ pmis-masters-management│
            │  schemas: masters.*    │
            │  (catalogs + templates)│
            └────────────────────────┘
                ▲   ▲   ▲
                │   │   │
        ┌───────┘   │   └───────────────────────┐
        │           │                           │
┌───────┴────────────┐  ┌──────────────────────┐ ┌──────────────────────────────┐
│ pmis-user-management│  │ pmis-project-management│ │ pmis-notification-management │
│ schemas: users.*    │  │ schemas: project.*    │ │ schemas: (none owned)         │
│ (auth+RBAC+OTP+     │  │ (projects/M/A/T/S/    │ │ (stateless dispatcher;        │
│  password reset)    │  │  comments/attachments/│ │  reads users+masters+project) │
│                     │  │  dashboard)           │ │                              │
└─────────────────────┘  └───────────────────────┘ └──────────────────────────────┘
        ▲                     ▲                          ▲
        │                     │                          │
        └─────────────────────┴──────────────────────────┘
                              │
                  reads RBAC from users.*
                  (role_permissions, user_roles,
                   user_role_assignments, revoked_tokens, etc.)
```

Each step ends with you approving the per-service `MIGRATION_LOG.md` before the next service starts (Phase 3 workflow per the original brief).

---

## §5 DB cutover strategy

### §5.1 Per-service schemas

Per Decision 4 + Q26 resolution: **single shared Postgres instance, four per-service schemas, named: `users`, `project`, `notification`, `masters`.** `users` replaces the reserved-word problem; no SQL quoting needed.

```sql
-- migrations/00_create_schemas.sql
CREATE SCHEMA IF NOT EXISTS users;
CREATE SCHEMA IF NOT EXISTS project;
CREATE SCHEMA IF NOT EXISTS notification;     -- empty post-refactor (no owned tables)
CREATE SCHEMA IF NOT EXISTS masters;

-- Application role
GRANT USAGE ON SCHEMA users, project, notification, masters TO pmis_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA users, project, notification, masters TO pmis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA users, project, notification, masters
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pmis_app;

-- DDL role (per Decision 4: DATABASE_URL_MIGRATIONS pattern)
GRANT USAGE, CREATE ON SCHEMA users, project, notification, masters TO pmis_ddl;
```

> Some table names will read as `users.users` (the `users` table in the `users` schema). Slightly redundant but unambiguous.

### §5.2 Tables per schema

| Schema | Tables |
|---|---|
| `users` | users, roles, permissions, user_roles, user_role_assignments, role_permissions, user_permissions, revoked_tokens, password_reset_tokens, otp_codes, notification_log |
| `project` | projects, project_audit_logs, project_vendors, milestones, milestone_dependencies, milestone_vendors, activities, activity_dependencies, activity_resources, tasks, task_dependencies, task_resources, subtasks, subtask_dependencies, subtask_resources, comments |
| `masters` | divisions, vendors, resource_types, project_categories, activity_types, activity_statuses, milestone_statuses, project_status_transitions, priorities, notification_templates |
| `notification` | (empty) |

**Cross-schema FK relationships preserved** (from today's referential integrity):
- `users.users.vendor_id` → `masters.vendors.id`
- `users.user_role_assignments.organization_id` → `masters.vendors.id`
- `users.user_role_assignments.project_id` → `project.projects.id`
- `project.project_vendors.vendor_id` → `masters.vendors.id`
- `project.activities.vendor_id` → `masters.vendors.id`
- `project.milestone_vendors.vendor_id` → `masters.vendors.id`
- `project.activity_resources.type_of_resource_id` → `masters.resource_types.id`
- `project.*.{created_by, updated_by, deleted_by}` → `users.users.id` (many)
- `users.notification_log` is owned by `users` per Doc-33 (audit log of issued notifications, not the template — the template lives in `masters.notification_templates`).

### §5.3 Cutover SQL outline

```sql
-- migrations/01_copy_data.sql (executed against prod during maintenance window)
BEGIN;

-- Step 1 (out of band): pg_dump snapshot taken by devops; explicit operator
--                       checkbox in docs/CUTOVER_RUNBOOK.md (per Q32).
-- Step 2 (out of band): each service runs `alembic upgrade head` to create
--                       empty target tables in its schema.

SET CONSTRAINTS ALL DEFERRED;

-- users.* (copy in dependency-safe order)
INSERT INTO users.users                  SELECT * FROM public.users;
INSERT INTO users.roles                  SELECT * FROM public.roles;
INSERT INTO users.permissions            SELECT * FROM public.permissions;
INSERT INTO users.user_roles             SELECT * FROM public.user_roles;
INSERT INTO users.role_permissions       SELECT * FROM public.role_permissions;
INSERT INTO users.user_permissions       SELECT * FROM public.user_permissions;
INSERT INTO users.user_role_assignments  SELECT * FROM public.user_role_assignments;
INSERT INTO users.revoked_tokens         SELECT * FROM public.revoked_tokens;
INSERT INTO users.password_reset_tokens  SELECT * FROM public.password_reset_tokens;
INSERT INTO users.otp_codes              SELECT * FROM public.otp_codes;
INSERT INTO users.notification_log       SELECT * FROM public.notification_log;

-- masters.*
INSERT INTO masters.divisions              SELECT * FROM public.divisions;
INSERT INTO masters.vendors                SELECT * FROM public.vendors;
INSERT INTO masters.resource_types         SELECT * FROM public.resource_types;
INSERT INTO masters.project_categories     SELECT * FROM public.project_categories;
INSERT INTO masters.activity_types         SELECT * FROM public.activity_types;
INSERT INTO masters.activity_statuses      SELECT * FROM public.activity_statuses;
INSERT INTO masters.milestone_statuses     SELECT * FROM public.milestone_statuses;
INSERT INTO masters.project_status_transitions SELECT * FROM public.project_status_transitions;
INSERT INTO masters.priorities             SELECT * FROM public.priorities;
INSERT INTO masters.notification_templates SELECT * FROM public.notification_templates;

-- project.*
INSERT INTO project.projects               SELECT * FROM public.projects;
INSERT INTO project.project_audit_logs     SELECT * FROM public.project_audit_logs;
INSERT INTO project.project_vendors        SELECT * FROM public.project_vendors;
INSERT INTO project.milestones             SELECT * FROM public.milestones;
INSERT INTO project.milestone_dependencies SELECT * FROM public.milestone_dependencies;
INSERT INTO project.milestone_vendors      SELECT * FROM public.milestone_vendors;
INSERT INTO project.activities             SELECT * FROM public.activities;
INSERT INTO project.activity_dependencies  SELECT * FROM public.activity_dependencies;
INSERT INTO project.activity_resources     SELECT * FROM public.activity_resources;
INSERT INTO project.tasks                  SELECT * FROM public.tasks;
INSERT INTO project.task_dependencies      SELECT * FROM public.task_dependencies;
INSERT INTO project.task_resources         SELECT * FROM public.task_resources;
INSERT INTO project.subtasks               SELECT * FROM public.subtasks;
INSERT INTO project.subtask_dependencies   SELECT * FROM public.subtask_dependencies;
INSERT INTO project.subtask_resources      SELECT * FROM public.subtask_resources;
INSERT INTO project.comments               SELECT * FROM public.comments;

-- Update autoincrement sequences for integer-PK tables
SELECT setval(pg_get_serial_sequence('users.roles', 'id'),
              (SELECT MAX(id) FROM users.roles));
SELECT setval(pg_get_serial_sequence('users.user_role_assignments', 'id'),
              (SELECT MAX(id) FROM users.user_role_assignments));
SELECT setval(pg_get_serial_sequence('users.password_reset_tokens', 'id'),
              (SELECT MAX(id) FROM users.password_reset_tokens));
SELECT setval(pg_get_serial_sequence('users.otp_codes', 'id'),
              (SELECT MAX(id) FROM users.otp_codes));
SELECT setval(pg_get_serial_sequence('users.notification_log', 'id'),
              (SELECT MAX(id) FROM users.notification_log));
SELECT setval(pg_get_serial_sequence('masters.divisions', 'id'),
              (SELECT MAX(id) FROM masters.divisions));
SELECT setval(pg_get_serial_sequence('masters.project_categories', 'id'),
              (SELECT MAX(id) FROM masters.project_categories));
SELECT setval(pg_get_serial_sequence('masters.activity_types', 'id'),
              (SELECT MAX(id) FROM masters.activity_types));
SELECT setval(pg_get_serial_sequence('masters.activity_statuses', 'id'),
              (SELECT MAX(id) FROM masters.activity_statuses));
SELECT setval(pg_get_serial_sequence('masters.milestone_statuses', 'id'),
              (SELECT MAX(id) FROM masters.milestone_statuses));
SELECT setval(pg_get_serial_sequence('masters.project_status_transitions', 'id'),
              (SELECT MAX(id) FROM masters.project_status_transitions));
SELECT setval(pg_get_serial_sequence('masters.notification_templates', 'id'),
              (SELECT MAX(id) FROM masters.notification_templates));
SELECT setval(pg_get_serial_sequence('project.project_audit_logs', 'id'),
              (SELECT MAX(id) FROM project.project_audit_logs));

COMMIT;

-- Step 3: legacy permission cleanup (Q25)
\i 03_cleanup_permissions.sql

-- Step 4: legacy public.* tables intentionally LEFT IN PLACE during burn-in.
-- 02_drop_legacy.sql is run only after 7+ days of clean operation.
```

```sql
-- migrations/03_cleanup_permissions.sql
DELETE FROM users.permissions
WHERE code LIKE 'meetings:%'
   OR code LIKE 'work_packages:%'
   OR code LIKE 'work_package_types:%';

DELETE FROM users.role_permissions
WHERE permission_code LIKE 'meetings:%'
   OR permission_code LIKE 'work_packages:%'
   OR permission_code LIKE 'work_package_types:%';

DELETE FROM users.user_permissions
WHERE permission_code LIKE 'meetings:%'
   OR permission_code LIKE 'work_packages:%'
   OR permission_code LIKE 'work_package_types:%';

DROP TABLE IF EXISTS public.project_members CASCADE;     -- Q12
```

```sql
-- migrations/02_drop_legacy.sql  (POST burn-in, 7+ days clean)
BEGIN;
DROP TABLE IF EXISTS public.work_packages CASCADE;
DROP TABLE IF EXISTS public.work_package_types CASCADE;
DROP TABLE IF EXISTS public.meeting_agenda_items CASCADE;
DROP TABLE IF EXISTS public.meetings CASCADE;
DROP TABLE IF EXISTS public.meeting_participants CASCADE;

-- Each migrated table: drop after burn-in confirmation
DROP TABLE IF EXISTS public.users CASCADE;
DROP TABLE IF EXISTS public.roles CASCADE;
-- (one DROP per table migrated in §5.3)
COMMIT;
```

### §5.4 Downtime estimate

- Schema CREATE: <1s
- Per-service alembic upgrade (empty tables): ~10–30s total
- Data copy (moderate-sized DB): **5–15 minutes**
- Service startup + smoke test: **3–5 minutes**
- **Total expected downtime: 10–25 minutes.** Worst-case on a large DB: 60 min. Validated on staging first.

---

## §6 Shared-code strategy

### §6.1 What's duplicated

Per Decision 7 (no shared package, per-service duplicates) + Q11 (cross-schema ORM declarations):

| Code | Canonical location | Duplicated to |
|---|---|---|
| JWT encode/decode | `services/pmis-user-management/app/core/security.py` | all 3 other services (decode-only) |
| Argon2 password hashing | `services/pmis-user-management/app/core/security.py` | (user-svc only) |
| RBAC dependency factories | `services/pmis-user-management/app/core/rbac.py` | all 3 other services |
| Permission code constants | `services/pmis-user-management/app/core/permissions.py` | duplicated subsets per service |
| HAL response formatters | `services/pmis-user-management/app/core/response.py` | all 3 other services |
| Pagination helpers | `services/pmis-user-management/app/schemas/pagination.py` | all 3 other services |
| Soft-delete query helpers | `services/pmis-user-management/app/db.py` | project, masters |
| Cross-schema RBAC ORM declarations | original models in `services/pmis-user-management/app/models/*.py` | `_cross_schema.py` in the other three services |

### §6.2 Canonical-location headers (per §2.5)

Every duplicate file carries a header listing the canonical path and the other duplicates. See §2.5 for the format.

### §6.3 Drift protection — two CI gates

1. **`tools/check_canonical_drift.py`** runs in each service's CI. Diffs each service's `core/security.py`, `core/rbac.py`, `core/response.py`, `schemas/pagination.py` against user-svc's canonical. Differences fail CI unless allowlisted in `tools/canonical_allowlist.json` (rare).

2. **`tests/test_cross_schema_drift.py`** (Q24) lives in user-svc. Imports the `_cross_schema` mirror modules from the other three services and asserts column names + types match user-svc's canonical declarations. If column rename happens in user-svc without updating mirrors, this fails the user-svc PR.

---

## §7 Test strategy

### §7.1 Five layers

| Layer | Scope | Location | Tooling |
|---|---|---|---|
| Unit | Pure functions, validators, no DB | `services/<svc>/tests/unit/` | pytest |
| Integration | Route → controller → service → repo → real Postgres | `services/<svc>/tests/integration/` | pytest + docker-compose Postgres |
| Parity | Wire-level diff vs captured monolith fixtures | `services/<svc>/tests/parity/` | pytest + jsondiff |
| Cross-schema drift | Read-only mirrors agree with user-svc canonicals | `services/pmis-user-management/tests/test_cross_schema_drift.py` | pytest |
| Smoke (e2e) | login → list → create → fetch across all 4 services | `tests/smoke/` at repo root | pytest + httpx + docker-compose-test.yml |

### §7.2 Parity testing approach

1. **Pre-cutover**: `tools/capture_fixtures.py` runs against the running monolith (or a local Postgres dump copy per Q28), walks the 64 FE-called endpoints, saves request/response pairs to `tests/parity/<svc>/<endpoint>/<scenario>.json`.
2. **Per service**: `tests/parity/test_<resource>.py` re-issues each captured request against the new service, diffs the response with tolerances.
3. **Tolerance config** at `tests/parity/tolerance.yml` allows: generated IDs, timestamps, HAL `_links` URLs, list ordering on unsorted endpoints, expected-removed Deprecation headers.

### §7.3 Test data baseline (Q28)

Per your answer: **read-only access to prod Postgres; take a local dump for testing**, never modify the server. `tools/capture_fixtures.py` documents the dump command (`pg_dump --schema-only ...` + sanitization step) and the `psql` import to a local Postgres.

### §7.4 Coverage bar

- Unit: 80% of services + helpers
- Integration: every route handler hit ≥1×
- Parity: all 64 FE-called endpoints + the 5 unobserved candidates (Q4) once grep confirms they're live
- Cross-schema drift: 100%, every PR

---

## §8 Rollback plan

### §8.1 Atomic rollback unit = the cutover event

| Window | Time | Action |
|---|---|---|
| Pre-cutover (staging) | Days before maintenance window | Failure on staging → fix in code; cutover not initiated |
| In-cutover, post-copy, pre-startup | After data copy, before `docker-compose up` | Drop new schemas, abort. Monolith stays up. **No user impact.** |
| In-cutover, services started, smoke test failing | After services start, smoke test fails | Stop new compose, drop new schemas (`public.*` is untouched), restart monolith, flip FE env var back. **~5–10 min recovery.** |
| Post-burn-in (7+ days) | After 02_drop_legacy.sql runs | Per-service rollback **not** clean. Forward-only; restore from backup if catastrophic. |

### §8.2 Rollback SQL

```sql
-- migrations/99_rollback.sql  (USE ONLY during cutover if smoke test fails)
BEGIN;
-- Out of band: docker-compose -f PMIS-refactor/docker-compose.yml down
DROP SCHEMA IF EXISTS users CASCADE;
DROP SCHEMA IF EXISTS project CASCADE;
DROP SCHEMA IF EXISTS notification CASCADE;
DROP SCHEMA IF EXISTS masters CASCADE;
COMMIT;
-- Out of band: cd C:\Programming\PMIS\PMIS-OpenProject && docker-compose up -d
-- Out of band: revert FE VITE_API_BASE_URL to monolith
```

Recovery time: 5–10 min. `public.*` is unmodified throughout.

### §8.3 Post-burn-in changes

After `02_drop_legacy.sql` runs, the new app is the system of record. Schema changes after that use standard alembic upgrade/downgrade pairs; downgrade is the per-change rollback unit.

---

## §9 Breaking changes

### §9.1 Path scheme

All FE-called endpoints change prefix from `/api/v3/*` to `/<service>/*` AND get verb suffixes (§2.4). FE update: one file (`src/api/endpoint.js`), ~64 entries, find-replace plus suffix-append. See §2.4 for the full path mapping.

### §9.2 Deleted endpoints (FE removes call sites)

- `/api/v3/users/{id}/roles/{role_id}` (legacy assign-role) → use `/user/users/{id}/role-assignments/create`
- `/api/v3/users/{id}/roles` (legacy role list) → use `/user/users/{id}/role-assignments/list`
- `/api/v3/roles/*` (legacy roles router, 9 routes) → use `/user/roles/*` with new verb suffixes
- `/api/v3/permissions/*` (legacy permissions router, 5 routes) → use `/user/permissions/*`
- `/api/v3/projects/{uuid}/memberships/*` (legacy memberships, 4 routes; table already migrated)
- All `/api/v3/vendors/*`, `/api/v3/divisions`, `/api/v3/resource_types`, `/api/v3/project_status_transitions` (legacy catalogs router) → unified into `/masters/*`

### §9.3 Removed features

- **Work packages** (6 routes + 2 tables): user-flagged legacy
- **Work package types** (5 routes + 1 table): user-flagged legacy
- **Meetings** (13 routes + 3 tables): user-flagged legacy
- `MEETINGS_*`, `WORK_PACKAGES_*`, `WORK_PACKAGE_TYPES_*` permission codes dropped from `users.permissions`

### §9.4 Auth-behavior changes

- **Pre-Doc-26 int-id JWT guard dropped** (Q17). All sessions older than refresh-expire (7 days) are already invalid; no real protection lost.
- **`UNIVERSAL_OTP_ENABLED=True` in `ENV=production` raises startup error** (Q14).

### §9.5 OTP flow changes

- OTP storage moves from notification-svc's in-process dict to `users.otp_codes` (Q13).
- `/notification/otp/send` and `/notification/otp/verify` retained for one release cycle as deprecated aliases; the canonical paths are `/user/users/login/send-otp` and `/user/users/login/verify-otp`.
- Mid-OTP-flow users at cutover lose their session and re-login.

### §9.6 Masters RBAC — granular per-catalog permissions (Option C)

Per the refined Option C decision: each catalog gets its own `<catalog>:read` and `<catalog>:manage` permission code. RBAC is enforced at every endpoint; defaults grant reads broadly so pickers work for all logged-in roles.

**Single endpoint pattern per catalog** (no `/picker` variant — that's superseded):
- `GET /masters/<resource>/list` — requires `<catalog>:read`
- `GET /masters/<resource>/{id}/details` — requires `<catalog>:read`
- `POST /masters/<resource>/create` — requires `<catalog>:manage`
- `PATCH /masters/<resource>/{id}/update` — requires `<catalog>:manage`
- `DELETE /masters/<resource>/{id}/delete` — requires `<catalog>:manage`
- `POST /masters/<resource>/{id}/restore` — requires `<catalog>:manage`

**Permission codes** (defined in `services/pmis-masters-management/app/core/permissions.py`; seeded into `users.permissions` by user-svc's bootstrap migration):

| Catalog | Read perm | Manage perm |
|---|---|---|
| divisions | `divisions:read` | `divisions:manage` |
| vendors | `vendors:read` | `vendors:manage` |
| resource_types | `resource_types:read` | `resource_types:manage` |
| priorities | `priorities:read` | `priorities:manage` |
| project_categories | `project_categories:read` | `project_categories:manage` |
| activity_types | `activity_types:read` | `activity_types:manage` |
| activity_statuses | `activity_statuses:read` | `activity_statuses:manage` |
| milestone_statuses | `milestone_statuses:read` | `milestone_statuses:manage` |
| project_status_transitions | `project_status_transitions:read` | `project_status_transitions:manage` |
| notification_templates | `notification_templates:read` | `notification_templates:manage` |

**Default role grants** (will be finalized during user-svc port — Q26 territory). First-pass default: all `<catalog>:read` permissions granted to every standard role (`super_admin`, `admin`, `org_admin`, `project_admin`, `project_member`, `division_member`) so pickers work out of the box. `<catalog>:manage` permissions granted only to `super_admin` + `admin` initially. Per-role customization can be applied via the role-permission management endpoints in user-svc.

**Scoping beyond permission codes:** the user has indicated additional read-scoping (e.g. "user only sees vendors in their organization") will be applied as **service-layer filters**, NOT as additional permission codes. This scoping is row-level and lives in `services/pmis-masters-management/app/services/<catalog>_service.py` — list queries inspect `request.state.user_id` / `vendor_id` / `is_admin` and narrow results. The exact filters are a Phase-3 user-svc-port discussion (the user explicitly deferred this).

**Removed:** `MASTER_DATA_VIEW` and `MASTER_DATA_MANAGE` are NOT used by masters-svc routes. They remain in `users.permissions` for back-compat during cutover but are no longer required for any new endpoint. They can be dropped post burn-in via a follow-up migration if no other service uses them.

**Migration impact:**
- `migrations/03_cleanup_permissions.sql` adds the 20 new permission codes to `users.permissions` (idempotent INSERT with ON CONFLICT DO NOTHING). The role-permission grants (which standard role gets which `<catalog>:read`) is owned by the user-svc bootstrap data-migration.
- Existing `master_data:view` / `master_data:manage` rows in `role_permissions` / `user_permissions` are left untouched during cutover (back-compat); orphaned in a follow-up.

### §9.7 Response shapes

- **No field renames** (per Q1 clarification). `vendor_id`, `vendor_code`, etc. stay on the wire. FE labels them "Organization".
- Per-service response-envelope normalization may produce small differences (consistent `code`+`message`+`details` in error responses; consistent HAL Collection shape). Parity tests catch unexpected changes.

### §9.8 Operational changes

- Boot-time DDL removed (Q16). Devops runs `alembic upgrade head` per service explicitly during deploys.
- Bootstrap data is a separate alembic data-migration (Q21). New environments need an explicit `alembic upgrade <bootstrap_rev>` to seed admin + master catalogs.
- Per-service alembic version tables: `alembic_version_users`, `alembic_version_project`, `alembic_version_notification`, `alembic_version_masters`.

---

## §10 Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Cross-schema FK fails during data copy (out-of-order rows / missing target) | H | H | (a) `SET CONSTRAINTS ALL DEFERRED` during copy. (b) Stage on staging-DB with cloned prod data. (c) Copy order matches dependency graph (`masters` → `users` → `project`). |
| 2 | Staging DB diverges from prod at cutover time, masking real issues | M | H | Clone prod into staging ≤24h before cutover. Re-run full parity test suite on fresh clone. |
| 3 | FE not updated in time; users hit 404s on old paths | M | H | Per Q27, **cutover happens after backend is locally verified via Swagger**; FE integration is the next step before UAT. Cutover timing controlled. |
| 4 | Cross-schema RBAC drift silently breaks auth | M | H | Q24 CI test imports read-only mirrors and asserts columns match. Plus §2.5 source-level warning headers ensure the developer sees the danger before they break it. |
| 5 | Alembic incomplete-chain regression (current user-svc bug doesn't carry over) | L | H | Each service's initial bootstrap migration creates every owned table from scratch against empty DB. CI runs `alembic upgrade head` against empty Postgres on every PR. |
| 6 | Notification dispatch breakage during cutover (monolith was an inbound caller for some flows) | M | M | notification-svc retains `/api/v1/notifications/*` aliases for 30 days (deprecated). Drop after burn-in. |
| 7 | OTP-in-flight users lose session at cutover | M | L | Cutover off-hours; pre-announce 15-min unavailability. |
| 8 | `UNIVERSAL_OTP_ENABLED` accidentally true in prod | L | H | Startup error in each service when `ENV=production` + flag=True (Q14). |
| 9 | Real attachment >25 MB exists; uploads break | L | M | Audit `comments.attachments` size in DB pre-cutover; raise `MAX_UPLOAD_MB` if needed. |
| 10 | Burn-in `public.*` tables confuse developers | M | L | `MIGRATION_GUIDE.md` + `MIGRATION_LOG.md` make burn-in explicit; `02_drop_legacy.sql` is operator-gated. |
| 11 | Granular catalog-read permissions not granted to a role at cutover; that role's FE pickers break | M | M | Per §9.6 Option C, user-svc bootstrap migration seeds all `<catalog>:read` codes and grants them to every standard role by default. Operator check during cutover: confirm `users.role_permissions` contains the catalog-read entries for `org_admin` / `project_admin` / `project_member` / `division_member`. |

---

## §11 Documentation deliverables

### §11.1 `docs/MIGRATION_GUIDE.md`

Operator-facing how-to. Sections:
1. **What this migration is** (one paragraph)
2. **Prerequisites** (Postgres version, Docker version, disk space for staging clone)
3. **Pre-cutover checklist** (staging validated, fixtures captured, FE branch ready, default-role `MASTER_DATA_VIEW` confirmed, snapshot taken)
4. **Cutover sequence** (links to `CUTOVER_RUNBOOK.md` for the SQL-level steps)
5. **Burn-in monitoring** (what to watch in logs; what counts as a clean week)
6. **Post-burn-in cleanup** (`02_drop_legacy.sql` step)
7. **Rollback procedure** (§8)
8. **Per-service migration notes** (links to each service's `MIGRATION_LOG.md`)

### §11.2 `docs/DEPLOY_GUIDE.md`

**ILLUSTRATIVE** — devops adapts. Sections:
1. **What's in this guide** (one paragraph: this is a reference, not a runbook)
2. **Local docker-compose** (single command bring-up of all 6 containers)
3. **Per-service environment variables** (table per service)
4. **Health/readiness probes** (`/health` + `/ready` endpoints, expected response shape)
5. **Alembic migration on deploy** (`docker run --rm pmis-<svc>-management alembic upgrade head`)
6. **Logging output format** (JSON in prod; configurable via `LOG_FORMAT`)
7. **What devops decides** (TLS, reverse proxy choice, secrets management, backup strategy, monitoring, alerting)

### §11.3 `docs/OPENAPI_QUALITY.md` — Swagger quality bar (per your point 4)

Phase 3 checklist that every endpoint must pass before its service's `MIGRATION_LOG.md` is approved:

- [ ] Route decorator has `summary` (≤60 chars, sentence case, no trailing period)
- [ ] Route decorator has `description` (one paragraph: what it does, when to call, what it returns, key side effects)
- [ ] Tags grouped by resource (e.g. `tags=["users"]`, not `tags=["api"]`)
- [ ] Request body uses Pydantic schema with field-level `description` on each `Field(...)`
- [ ] Response model declared via `response_model=...` (or `response_model_exclude_none=True` where applicable)
- [ ] Status codes documented via `responses={...}` for 4xx/5xx returns (e.g. `409: {"description": "Login already in use"}`)
- [ ] File-upload endpoints use `UploadFile = File(...)` (NOT `str`) so Swagger shows a "Choose files" picker
- [ ] Deprecated endpoints are marked `deprecated=True` and `description` includes the successor URL
- [ ] Authentication requirement is visible in Swagger (the FastAPI `Depends(require_permission(...))` propagates automatically)

CI gate: a `tools/check_openapi_quality.py` script walks the generated OpenAPI spec and asserts every operation has summary+description+tags. Fails PRs that introduce empty descriptions.

### §11.4 `docs/MIGRATION_LOG.template.md` — per-service Phase 3 deliverable

Each service gets its own filled-in copy after porting. Template:

```markdown
# pmis-<svc>-management — Migration Log

## Source
- monolith path: C:\Programming\PMIS\PMIS-OpenProject\app\api\v3\<resource>\…
- sibling extraction path (if any): C:\Programming\PMIS\PMIS-<svc>\…

## Endpoint port table
| METHOD | NEW PATH | HANDLER (new file:line) | SOURCE HANDLER (path:line) | NOTES |

## Models migrated
| Table | New model (file:line) | Source (path:line) | Schema changes |

## Migrations added
| Revision | Description |

## Tests
| Layer | Count | Coverage |

## Open issues
| Issue | Disposition |

## Approval
- [ ] Routes match endpoint plan
- [ ] OpenAPI quality bar passes
- [ ] Integration tests pass against staging-DB
- [ ] Parity tests pass (or tolerated diffs documented)
- [ ] Cross-schema drift test passes
- [ ] User approval to proceed to next service
```

---

## §12 Q26–Q35 resolutions

| Q | Answer | Resolution |
|---|---|---|
| Q26 | "go with your recommendation" → **`users`** schema (per your point 8) | Avoid the reserved-word problem; `users.users` slightly redundant but unambiguous. Applied throughout §5. |
| Q27 | "done post locally verifying backend works through swagger, then FE integrated, then UAT" | Cutover happens after backend swagger-verified locally; then FE switchover; then UAT. Order locked into `CUTOVER_RUNBOOK.md`. |
| Q28 | "read-only access to prod; take a local dump for testing" | Documented in §7.3 and as a prerequisite in `MIGRATION_GUIDE.md`. No prod modifications. |
| Q29 | "yes works for me" → start with notification-svc | Confirmed. Phase 3 implementation order: notification → masters → user → project. |
| Q30 | "follow the kind of logic that the notification service in PMIS original implementation follows" | Controllers exist for every resource (matches notification-svc's legacy email/sms/otp pattern), thin: unpack request → call service → shape response. Documented in §1.2. |
| Q31 | "follow recommendation" → **`postgres:16-alpine`** | Pinned in docker-compose. |
| Q32 | "yes, add step" | `pg_dump` step explicitly added to `CUTOVER_RUNBOOK.md` with operator checkbox. |
| Q33 | "recommendation follow" → env var | `SUPERADMIN_BOOTSTRAP_PASSWORD` env var consumed by alembic bootstrap data-migration; hashed with argon2 inside the migration; env var then unset. |
| Q34 | "follow recommendation" → scaffold tests, generate fixtures later | Phase 3 initial commit ships test scaffolding + `capture_fixtures.py`; fixtures generated in a follow-up commit after first service ports. |
| Q35 | "use prefixed names; don't do any deployment etc" → **`pmis-<svc>-management`** | Service names in docker-compose: `pmis-user-management`, `pmis-project-management`, `pmis-notification-management`, `pmis-masters-management`, `pmis-frontend`. docker-compose.yml is a **guideline for devops** — included as reference, not as a deployment script. |

---

## §13 Phase 3 kick-off plan

When you say "proceed to implementation":

1. **Create the directory skeleton** under `PMIS-refactor/`:
   - Empty `services/pmis-{user,project,notification,masters}-management/app/{models,schemas,repositories,services,controllers,routes,middleware,core,utilities}/` with package markers.
   - `nginx/` with the illustrative configs from §3.
   - `migrations/` with the SQL scripts from §5 (executable but not yet run).
   - `tools/` skeletons (placeholder modules).
   - `docs/` with the four guide files from §11 (skeletons; filled in as work progresses).
   - Root `docker-compose.yml`, `docker-compose.staging.yml`, `docker-compose.test.yml`, `.env.example`, `.gitignore`, `README.md`.

2. **Implement pmis-notification-management first** (your Q29 yes):
   - Port the 6 dispatch + cron + health endpoints with the verb-suffix names from §2.4.
   - Wire the cross-schema reads for masters.notification_templates and users.* tables.
   - Drop OTP storage; verify the endpoints are deprecation-aliased.
   - Pass: `alembic upgrade head` (no-op — no owned tables), unit tests, integration tests, OpenAPI quality check.
   - Fill `MIGRATION_LOG.md` per §11.4 template, with source `path:line` citations for each ported handler.
   - **Stop and present for your approval before starting masters-svc.**

3. **Then masters-svc, then user-svc, then project-svc** — each gated by your approval per the original brief's Phase 3 workflow.

Nothing is touched in `C:\Programming\PMIS\`. Nothing modifies any code under `services/`, `migrations/`, or `nginx/` until you approve this revised plan.

---

## Status

- ✅ Folder anatomy fully documented (§1.2 per-folder table)
- ✅ Modern Pydantic v2 + SQLAlchemy 2.0 patterns specified (§2.1, §2.2)
- ✅ FastAPI file-upload UX + Swagger quality bar (§2.3, §11.3)
- ✅ Endpoint naming with verb suffixes applied throughout (§2.4)
- ✅ Source-level cross-schema drift warnings (§2.5)
- ✅ Nginx reframed as illustrative (§3)
- ✅ Schema rename to `users` (§5.1)
- ✅ Masters RBAC corrected (§9.6)
- ✅ Migration + deploy guide deliverables defined (§11.1, §11.2)
- ✅ Service names prefixed `pmis-*` (§1.1)
- ✅ Q26–Q35 closed (§12)

Awaiting your **"proceed to implementation"** to begin the Phase 3 scaffold + notification-svc port.
