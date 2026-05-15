# PMIS-OpenProject (Monolith) Audit

Source root: `C:\Programming\PMIS\PMIS-OpenProject\`. Sibling extraction services live
under `C:\Programming\PMIS\PMIS-user-management`, `C:\Programming\PMIS\PMIS-notification-service`,
`C:\Programming\PMIS\PMIS-project-management`.

This is a read-only inventory. Every concrete claim cites `path:line`. Prose uses the
prefixes `OBSERVED:` (read directly), `INFERRED:` (deduced from observed evidence), and
`[UNVERIFIED]` (could not confirm — flagged for follow-up).

---

## 1. Tech & dependencies

OBSERVED:

- **Python version**: 3.12-slim — `C:\Programming\PMIS\PMIS-OpenProject\Dockerfile:1` (`FROM python:3.12-slim`). `requirements.txt:1-3` header is `pip-compile with Python 3.12`.
- **App server**: uvicorn 0.44.0 — `requirements.txt:178`. Container CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000` at `Dockerfile:25`.
- **FastAPI**: 0.135.3 `[standard]` — `requirements.txt:52-53`. Starlette 1.0.0 (`requirements.txt:154`).
- **SQLAlchemy**: 2.0.49 — `requirements.txt:152`.
- **Alembic**: 1.18.4 — `requirements.txt:189`. Pinned outside the pip-compile block (manually appended).
- **DB drivers**: `psycopg2-binary==2.9.9` (`requirements.txt:188`); SQLite via stdlib for dev (`pmis.db` exists in repo root — `bench_pmis_local.db`, `pmis.db`).
- **Auth/crypto libs**:
  - `python-jose[cryptography]==3.5.0` — JWT (`requirements.txt:126`). Imported at `app\core\security.py:9` (`from jose import JWTError, jwt, ExpiredSignatureError`).
  - `passlib[argon2]==1.7.4` + `argon2-cffi==25.1.0` — password hashing (`requirements.txt:91`, `:18`). Used via `argon2.PasswordHasher` at `app\core\security.py:7-13`.
- **HTTP client (outbound)**: `httpx==0.28.1` (`requirements.txt:70`) — used by both proxy clients and the notification HTTP backend (cites in §7).
- **File-upload**: `python-multipart==0.0.24` (`requirements.txt:128`); content-type sniffing by magic bytes via `filetype==1.2.0` (`requirements.txt:195`) — used by `app\shared\file_signature.py`.
- **Email validation**: `email-validator==2.3.0` (`requirements.txt:47`).
- **Background tasks**: NONE OBSERVED — no Celery / RQ / arq / APScheduler dependency in requirements.txt. INFERRED: there is no async-job framework; everything runs synchronously in the request cycle. The doc-35 retention cron mentioned in `app\core\config.py:194` (`ATTACHMENTS_RETENTION_DAYS`) is referred to as "(future) cleanup cron" — not implemented.
- **Storage**: local filesystem layer (`app\infrastructure\storage`) with optional NFS mount-point and an optional external file-server (URL prefix). Configured by `ATTACHMENTS_*` and `FILE_SERVER_*` env vars at `app\core\config.py:161-299`.
- **Email/SMS**: outbound notifications dispatched via HTTP to the standalone notification-service (port 8002 implied by env). Mock backend writes to `notification_log` table only. See `app\shared\notifications.py:339-373`.
- **Sentry SDK**: `sentry-sdk==2.57.0` (`requirements.txt:146`) — comes in via `fastapi-cloud-cli`; INFERRED: not actively configured anywhere in `app/` (no `sentry_sdk.init` call found in module scan — needs verification with full grep).

---

## 2. Entry point & startup

OBSERVED:

- **FastAPI factory**: `app\main.py:62-68` — `app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, ...)`.

- **Router includes** (all in `app\main.py`):
  - `app.include_router(api_v3_router)` — `app\main.py:165`.
  - `@app.get("/files/{storage_key:path}", ...)` — `app\main.py:188` (conditional on `settings.FILE_SERVER_LOCAL_FALLBACK_ENABLED`).
  - `@app.get("/health", tags=["health"])` — `app\main.py:345`.
  - `@app.get("/", tags=["root"])` — `app\main.py:440`.
- **api_v3_router** is built at `app\api\router.py:52` (`api_v3_router = APIRouter(prefix="/api/v3")`) and includes 20+ sub-routers (full list in `app\api\router.py:59-110`).

- **Middleware order** (Starlette wraps LIFO; last add = outermost). All in `app\main.py`:
  - `app.add_middleware(LoggingMiddleware)` — `app\main.py:90` (innermost).
  - `app.add_middleware(AuthenticationMiddleware)` — `app\main.py:91`.
  - `app.add_middleware(UserServiceProxyMiddleware)` — `app\main.py:92`.
  - `app.add_middleware(NotificationServiceProxyMiddleware)` — `app\main.py:93`.
  - `app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])` — `app\main.py:96-102` (outermost).
  - Inline docstring at `app\main.py:71-89` documents the exact outer→inner stack.

- **Exception handlers**: `@app.exception_handler(DomainError)` at `app\main.py:106-132`; `@app.exception_handler(Exception)` at `app\main.py:135-161`.

- **Lifespan**: `asynccontextmanager lifespan(app)` — `app\main.py:28-58`. Logs UNIVERSAL_OTP warning when enabled (`app\main.py:46-52`). Calls `init_db()` at `app\main.py:38`.

- **Env vars consumed** (every field on the Pydantic `Settings` class in `app\core\config.py`):
  - `APP_NAME`, `APP_VERSION`, `DEBUG` — `config.py:14-16`
  - `SECRET_KEY` — `config.py:19-22`; `ALGORITHM` (`:23`); `ACCESS_TOKEN_EXPIRE_MINUTES=120` (`:33`); `REFRESH_TOKEN_EXPIRE_DAYS=7` (`:35`); `REFRESH_TOKEN_GRACE_SECONDS=120` (`:42`)
  - `SUBTASK_MAX_NESTING_DEPTH` — `:50`
  - `DATABASE_URL` — `:53-56`
  - `DATABASE_URL_MIGRATIONS` — `:74-81`
  - `MIGRATIONS_AUTORUN=True` — `:96-102`
  - `MIGRATIONS_REQUIRED=True` — `:118-125`
  - `CORS_ORIGINS=["*"]` — `:128`
  - `DEFAULT_PAGE_SIZE=20`, `MAX_PAGE_SIZE=100` — `:131-132`
  - `BOOTSTRAP_ADMIN_LOGIN`, `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` — `:136-138` (note: bootstrap of `admin` user is disabled per doc 42b; see `app\infrastructure\db\session.py:634-641`)
  - `BOOTSTRAP_SUPERADMIN_LOGIN/EMAIL/PASSWORD` — `:145-147` (still used at boot — see `session.py:652-700`)
  - `ATTACHMENTS_STORAGE_BASE_PATH` (default `./local_uploads`) — `:161-168`
  - `ATTACHMENTS_MAX_BYTES=26214400` — `:171-174`
  - `ATTACHMENTS_ALLOWED_EXTENSIONS` — `:179-182`
  - `ATTACHMENTS_SUBDIR_STRATEGY="year_month"` — `:187-190`
  - `ATTACHMENTS_RETENTION_DAYS=90` — `:194-197`
  - `ATTACHMENTS_ON_UNAVAILABLE="fail"` — `:201-204`
  - `ATTACHMENTS_NFS_SERVER`, `ATTACHMENTS_NFS_EXPORT` — `:208-215`
  - `FRONTEND_BASE_URL` — `:229-237`
  - `FILE_SERVER_PUBLIC_BASE_URL` — `:258-267`
  - `FILE_SERVER_LOCAL_FALLBACK_ENABLED=True` — `:273-281`
  - `FILE_SERVER_BASE_URL`, `FILE_SERVER_AUTH_TOKEN` — `:288-299`
  - `REQUIRE_2FA=True` — `:308-311`
  - `OTP_TTL_SECONDS=300`, `OTP_RESEND_COOLDOWN_SECONDS=60`, `OTP_MAX_ATTEMPTS=5`, `OTP_CODE_LENGTH=6`, `OTP_HASH_PEPPER` — `:316-346`
  - `PASSWORD_RESET_TTL_SECONDS=3600` — `:349-352`
  - `NOTIFICATION_CLIENT="mock"` — `:358-361` (selects `mock` vs `http` backend)
  - `NOTIFICATION_SERVICE_URL` — `:366-369`
  - `UNIVERSAL_OTP_ENABLED=False` — `:387-394`; `UNIVERSAL_OTP_CODE="000000"` — `:395-402`
  - `USER_SERVICE_PROXY_ENABLED=False` — `:413-420`; `USER_SERVICE_URL` — `:421-427`; `USER_SERVICE_TIMEOUT_SECONDS=10.0` — `:428-434`
  - `NOTIFICATION_SERVICE_PROXY_ENABLED=False` — `:443-453`; `NOTIFICATION_SERVICE_TIMEOUT_SECONDS=10.0` — `:454-457`
  - `DIVISION_DEFAULT_EMAIL`, `DIVISION_DEFAULT_PHONE` — `:467-482`
  - All other `os.getenv` references go through this `Settings` object (`app\core\config.py:485` instantiates it as `settings`).

- **DB connection setup**:
  - Engine: `app\infrastructure\db\session.py:11-15` — `create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}, echo=settings.DEBUG)`.
  - `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)` — `session.py:18`.
  - `class Base(DeclarativeBase): pass` — `session.py:21-22`.
  - `get_db()` generator dep — `session.py:136-150`.
  - `init_db()` runs `alembic upgrade head` as a subprocess on Postgres (`session.py:209-280`), uses `Base.metadata.create_all(bind=engine)` on SQLite (`session.py:194-195`), then runs a vast SQLite "self-heal" ALTER-block (`session.py:282-619`).

- **Port**: 8000. `Dockerfile:23` (`EXPOSE 8000`), `Dockerfile:25` (CMD `--port 8000`), `docker-compose.yml:28-29` (`ports: - "8000:8000"`), and `app\main.py:465` (uvicorn `port=8000` in the `__main__` block).

---

## 3. Route inventory (FULL)

NOTE on tables: all paths are full paths after stacking router prefixes. `api_v3_router` adds `/api/v3` (`app\api\router.py:52`). Sub-router prefixes are noted with each row.

### users — `app\api\v3\users\routes.py` (router prefix `/users` → full prefix `/api/v3/users`)

| METHOD | PATH | HANDLER (file:line) | AUTH | RBAC PERMISSION | REQUEST SCHEMA | RESPONSE SCHEMA | DB TABLES TOUCHED | EXTERNAL/INTERNAL HTTP CALLS | NOTES |
|---|---|---|---|---|---|---|---|---|---|
| POST | /api/v3/users/introspect | users\routes.py:48 | public | none | IntrospectRequest | dict (token introspection) | revoked_tokens | none (local) | Public; proxied when USER_SERVICE_PROXY_ENABLED |
| POST | /api/v3/users/refresh | users\routes.py:68 | public | none | RefreshRequest | dict (new access+refresh) | users | none | Token rotation; proxied |
| POST | /api/v3/users/login | users\routes.py:88 | public | none | LoginRequest | dict | users, otp_codes | calls notification client if 2FA | Proxied |
| POST | /api/v3/users/login/send-otp | users\routes.py:111 | public (ephemeral token) | none | OtpSendRequest | dict | otp_codes, notification_log | notification HTTP | Proxied |
| POST | /api/v3/users/login/verify-otp | users\routes.py:128 | public | none | OtpVerifyRequest | dict | otp_codes, users | none | Universal-OTP backdoor via settings; Proxied |
| POST | /api/v3/users/forgot-password | users\routes.py:144 | public | none | ForgotPasswordRequest | dict | password_reset_tokens, notification_log | notification HTTP | Anti-enumeration always 200; Proxied |
| POST | /api/v3/users/reset-password | users\routes.py:159 | public | none | ResetPasswordRequest | dict | password_reset_tokens, users | none | Proxied |
| POST | /api/v3/users/logout | users\routes.py:177 | required | (auth only) | none | dict | revoked_tokens, users | none | Idempotent; Proxied |
| GET | /api/v3/users/me | users\routes.py:191 | required | (auth only) | n/a | dict | users | none | Proxied |
| POST | /api/v3/users/create | users\routes.py:210 | required | USERS_CREATE | UserCreateRequest | dict | users, user_role_assignments | none | Status 201; Proxied. **Overlap with sibling user-mgmt**. |
| GET | /api/v3/users | users\routes.py:229 | required | USERS_READ_ALL | UserListQuery | Collection | users | none | Paged; Proxied |
| GET | /api/v3/users/{user_id} | users\routes.py:268 | required | USERS_READ | n/a | dict | users | none | Accepts UUID or US- code; Proxied |
| PATCH | /api/v3/users/{user_id} | users\routes.py:292 | required | USERS_UPDATE | UserUpdateRequest | dict | users | none | Proxied |
| PATCH | /api/v3/users/{user_id}/password | users\routes.py:317 | required | USERS_UPDATE | UserPasswordUpdateRequest | dict | users | none | Proxied |
| DELETE | /api/v3/users/{user_id} | users\routes.py:342 | required | USERS_DELETE_ALL | n/a | dict | users (soft-delete) | none | Proxied |
| POST | /api/v3/users/{user_id}/restore | users\routes.py:369 | required | USERS_DELETE_ALL | n/a | dict | users | none | Proxied |
| GET | /api/v3/users/me/permissions | users\routes.py:428 | required | (auth only) | n/a | EffectivePermissions | user_roles, user_role_assignments, role_permissions, user_permissions | none | Proxied |
| GET | /api/v3/users/{user_id}/permissions | users\routes.py:453 | required | PERMISSIONS_READ | n/a | EffectivePermissions | (same) | none | Proxied |
| POST | /api/v3/users/{user_id}/permissions/{code} | users\routes.py:478 | required | RBAC_ASSIGN | n/a | dict | user_permissions | none | Proxied |
| DELETE | /api/v3/users/{user_id}/permissions/{code} | users\routes.py:511 | required | RBAC_ASSIGN | n/a | 204 | user_permissions | none | Proxied |
| GET | /api/v3/users/{user_id}/roles | users\routes.py:531 | required | PERMISSIONS_READ | n/a | Collection | user_roles, roles | none | Proxied |
| POST | /api/v3/users/{user_id}/roles/{role_id} | users\routes.py:554 | required | RBAC_ASSIGN | n/a | dict | user_roles, roles | none | Proxied |
| DELETE | /api/v3/users/{user_id}/roles/{role_id} | users\routes.py:585 | required | RBAC_ASSIGN | n/a | 204 | user_roles | none | Last-admin lockout protection (lines 604-615); Proxied |

NOTES (users):
- Every path under `/api/v3/users/*` is forwarded to PMIS-user-management when `USER_SERVICE_PROXY_ENABLED=true` — see prefix list at `app\shared\user_service_client.py:239-249` (`_PROXIED_PATH_PREFIXES`).
- **OVERLAP with PMIS-user-management**: the entire user surface duplicates the sibling service. The monolith is the rollback path; sibling is the planned canonical owner.

### projects — `app\api\v3\projects\routes.py` (prefix `/projects` → `/api/v3/projects`)

| METHOD | PATH | HANDLER | AUTH | RBAC | REQ | RES | TABLES | HTTP | NOTES |
|---|---|---|---|---|---|---|---|---|---|
| POST | /api/v3/projects/create | projects\routes.py:154 | req | PROJECTS_CREATE | ProjectCreateRequest (JSON or multipart) | dict | projects, project_vendors, comments, project_audit_logs | none | Dual JSON/multipart |
| PUT | /api/v3/projects/{project_uuid} | projects\routes.py:184 | req | PROJECTS_CREATE | ProjectUpsertRequest | dict | projects | none | Idempotent upsert by UUID |
| GET | /api/v3/projects | projects\routes.py:203 | req | PROJECTS_READ | ProjectListQuery | Collection | projects, project_vendors | none | |
| GET | /api/v3/projects/all | projects\routes.py:229 | req | PROJECTS_READ | ProjectListQuery | Collection | projects | none | Includes soft-deleted (admin view) |
| GET | /api/v3/projects/{project_uuid} | projects\routes.py:249 | req | PROJECTS_READ | n/a | dict | projects | none | |
| PATCH | /api/v3/projects/{project_uuid} | projects\routes.py:262 | req | PROJECTS_UPDATE (project-scoped) | ProjectUpdateRequest | dict | projects, project_audit_logs | none | |
| DELETE | /api/v3/projects/{project_uuid} | projects\routes.py:276 | req | PROJECTS_DELETE_ALL (project-scoped) | n/a | dict | projects (soft-delete) | none | |
| POST | /api/v3/projects/{project_uuid}/save | projects\routes.py:295 | req | PROJECTS_UPDATE (project-scoped) | n/a | dict | projects, project_audit_logs | none | Step-1 wizard "Save" |
| POST | /api/v3/projects/{project_uuid}/publish | projects\routes.py:308 | req | PROJECTS_PUBLISH (project-scoped) | n/a | dict | projects, project_audit_logs | none | |
| POST | /api/v3/projects/{project_uuid}/close | projects\routes.py:321 | req | PROJECTS_CLOSE (project-scoped) | ProjectCloseRequest | dict | projects, project_audit_logs | none | |
| GET | /api/v3/projects/{project_uuid}/role-assignments | projects\routes.py:343 | req | PROJECT_MEMBERS_READ | n/a | dict | user_role_assignments, roles, users, projects | none | **OVERLAP with PMIS-user-management** (doc 44 round 8 mirror) |
| GET | /api/v3/projects/{project_uuid}/assignable-users | projects\routes.py:404 | req | PROJECT_MEMBERS_READ | n/a | dict | users, user_role_assignments, roles, project_vendors, user_roles | none | |
| GET | /api/v3/projects/{project_uuid}/audit-logs | projects\routes.py:547 | req | PROJECTS_READ (project-scoped) | n/a | Collection | project_audit_logs, dependency tables, milestones/activities/tasks/subtasks | none | |
| GET | /api/v3/projects/{project_uuid}/attachments | projects\routes.py:788 | req | PROJECTS_READ | n/a | Collection | comments | none | |
| POST | /api/v3/projects/{project_uuid}/attachments | projects\routes.py:857 | req | COMMENTS_CREATE | multipart files[] | Collection | comments, project_audit_logs | none | |
| GET | /api/v3/projects/{project_uuid}/discussion-feed | projects\routes.py:961 | req | PROJECTS_READ | n/a | Collection | comments, milestones, activities, tasks, subtasks, users | none | |
| POST | /api/v3/projects/{project_uuid}/role-assignments | projects\routes.py:1146 | (proxy gate) | (delegated) | passthrough | passthrough | (user-mgmt owns) | **HTTP → PMIS-user-management** | Forwarding-only; calls `proxy_or_503` |
| DELETE | /api/v3/projects/{project_uuid}/role-assignments/{assignment_id} | projects\routes.py:1163 | (proxy gate) | (delegated) | passthrough | passthrough | (user-mgmt owns) | **HTTP → PMIS-user-management** | Forwarding-only |

NOTES (projects):
- The two role-assignment writes (POST/DELETE under `/projects/{id}/role-assignments`) explicitly forward to user-mgmt via `proxy_or_503` (`projects\routes.py:1134, :1151, :1168`). Listing remains a native handler — there's the duplication.
- **OVERLAP with PMIS-project-management**: project CRUD is the canonical target there.

### milestones — `app\api\v3\milestones\routes.py`

Two routers: `milestones_project_router(prefix="/projects", tags=["milestones"])` (`milestones\routes.py:26`) and `milestones_router(prefix="/milestones", tags=["milestones"])` (`:29`).

| METHOD | PATH | HANDLER | AUTH | RBAC | REQ | RES | TABLES | NOTES |
|---|---|---|---|---|---|---|---|---|
| POST | /api/v3/projects/{project_uuid}/milestones/create | milestones\routes.py:138 | req | MILESTONES_CREATE (proj-scoped) | MilestoneCreateRequest (JSON or multipart) | dict | milestones, milestone_dependencies, milestone_vendors, comments | dual-mode |
| GET | /api/v3/projects/{project_uuid}/milestones | milestones\routes.py:170 | req | MILESTONES_READ | MilestoneListQuery | Collection | milestones | |
| GET | /api/v3/milestones/{milestone_id} | milestones\routes.py:190 | req | MILESTONES_READ | n/a | dict | milestones | |
| PATCH | /api/v3/milestones/{milestone_id} | milestones\routes.py:203 | req | MILESTONES_UPDATE (proj-scoped) | MilestoneUpdateRequest | dict | milestones | |
| DELETE | /api/v3/milestones/{milestone_id} | milestones\routes.py:217 | req | MILESTONES_DELETE (proj-scoped) | n/a | dict | milestones (cascades) | |
| POST | /api/v3/milestones/{milestone_id}/restore | milestones\routes.py:230 | req | MILESTONES_RESTORE (proj-scoped) | n/a | dict | milestones | admin |

### activities — `app\api\v3\activities\routes.py`

Two routers: `activities_milestone_router(prefix="/milestones")`, `activities_router(prefix="/activities")` (`activities\routes.py:33-34`).

| METHOD | PATH | HANDLER | AUTH | RBAC | REQ | RES | TABLES | NOTES |
|---|---|---|---|---|---|---|---|---|
| POST | /api/v3/milestones/{milestone_id}/activities/create | activities\routes.py:109 | req | ACTIVITIES_CREATE (proj-scoped) | ActivityCreateRequest | dict | activities, activity_dependencies, comments | Doc-38 collapsed-create |
| GET | /api/v3/milestones/{milestone_id}/activities | activities\routes.py:129 | req | ACTIVITIES_READ | ActivityListQuery | Collection | activities | |
| GET | /api/v3/activities/{activity_id} | activities\routes.py:147 | req | ACTIVITIES_READ | n/a | dict | activities, activity_resources | |
| PATCH | /api/v3/activities/{activity_id} | activities\routes.py:156 | req | ACTIVITIES_UPDATE (proj-scoped) | ActivityUpdateRequest | dict | activities, activity_resources | |
| DELETE | /api/v3/activities/{activity_id} | activities\routes.py:168 | req | ACTIVITIES_DELETE (proj-scoped) | n/a | dict | activities (cascades) | |
| POST | /api/v3/activities/{activity_id}/restore | activities\routes.py:177 | req | ACTIVITIES_RESTORE (proj-scoped) | n/a | dict | activities | |

### tasks — `app\api\v3\tasks\routes.py`

| METHOD | PATH | HANDLER | AUTH | RBAC | REQ | RES | TABLES | NOTES |
|---|---|---|---|---|---|---|---|---|
| POST | /api/v3/activities/{activity_id}/tasks/create | tasks\routes.py:88 | req | TASKS_CREATE (proj-scoped) | TaskCreateRequest | dict | tasks, task_dependencies, task_resources, comments | Dual JSON/multipart |
| GET | /api/v3/activities/{activity_id}/tasks | tasks\routes.py:108 | req | TASKS_READ | TaskListQuery | Collection | tasks | |
| GET | /api/v3/tasks/{task_id} | tasks\routes.py:126 | req | TASKS_READ | n/a | dict | tasks, task_resources | |
| PATCH | /api/v3/tasks/{task_id} | tasks\routes.py:135 | req | TASKS_UPDATE (proj-scoped) | TaskUpdateRequest | dict | tasks, task_resources | |
| DELETE | /api/v3/tasks/{task_id} | tasks\routes.py:144 | req | TASKS_DELETE (proj-scoped) | n/a | dict | tasks (cascades subtasks) | |
| POST | /api/v3/tasks/{task_id}/restore | tasks\routes.py:153 | req | TASKS_RESTORE (proj-scoped) | n/a | dict | tasks | |

### subtasks — `app\api\v3\subtasks\routes.py`

| METHOD | PATH | HANDLER | AUTH | RBAC | REQ | RES | TABLES | NOTES |
|---|---|---|---|---|---|---|---|---|
| POST | /api/v3/tasks/{task_id}/subtasks/create | subtasks\routes.py:82 | req | SUBTASKS_CREATE (proj-scoped) | SubtaskCreateRequest | dict | subtasks, subtask_dependencies, subtask_resources, comments | |
| GET | /api/v3/tasks/{task_id}/subtasks | subtasks\routes.py:102 | req | SUBTASKS_READ | SubtaskListQuery | Collection | subtasks | |
| POST | /api/v3/subtasks/{parent_subtask_id}/subtasks/create | subtasks\routes.py:128 | req | SUBTASKS_CREATE (proj-scoped) | SubtaskCreateRequest | dict | subtasks | Nested subtask |
| GET | /api/v3/subtasks/{subtask_id} | subtasks\routes.py:150 | req | SUBTASKS_READ | n/a | dict | subtasks | |
| PATCH | /api/v3/subtasks/{subtask_id} | subtasks\routes.py:159 | req | SUBTASKS_UPDATE (proj-scoped) | SubtaskUpdateRequest | dict | subtasks | |
| DELETE | /api/v3/subtasks/{subtask_id} | subtasks\routes.py:168 | req | SUBTASKS_DELETE (proj-scoped) | n/a | dict | subtasks | |
| POST | /api/v3/subtasks/{subtask_id}/restore | subtasks\routes.py:177 | req | SUBTASKS_RESTORE (proj-scoped) | n/a | dict | subtasks | |

### tree — `app\api\v3\tree\routes.py` (prefix `/projects`)

| METHOD | PATH | HANDLER | AUTH | RBAC | REQ | RES | TABLES | NOTES |
|---|---|---|---|---|---|---|---|---|
| GET | /api/v3/projects/{project_uuid}/tree | tree\routes.py:29 | req | PROJECTS_READ | n/a | dict | milestones, activities, tasks, subtasks (+resource tables) | Full M/A/T/S tree |

### vendors — `app\api\v3\vendors\routes.py` (prefix `/vendors`)

Marked "LEGACY — superseded by doc 20" in the file docstring (`vendors\routes.py:1`). Every endpoint stamps `Deprecation: true` pointing at `/api/v3/master/vendors/*`.

| METHOD | PATH | HANDLER | AUTH | RBAC | REQ | RES | TABLES | NOTES |
|---|---|---|---|---|---|---|---|---|
| GET | /api/v3/vendors | vendors\routes.py:242 | req | VENDORS_READ | active_only? | Collection | vendors, project_vendors, projects, user_role_assignments | DEPRECATED |
| GET | /api/v3/vendors/{vendor_id} | vendors\routes.py:313 | req | VENDORS_READ | n/a | dict | (same) | DEPRECATED |
| POST | /api/v3/vendors/create | vendors\routes.py:396 | req | VENDORS_MANAGE | VendorCreateRequest | dict | vendors, project_vendors, user_role_assignments | DEPRECATED |
| PATCH | /api/v3/vendors/{vendor_id} | vendors\routes.py:491 | req | (body-shape gate: VENDORS_MANAGE or RBAC_ASSIGN) | VendorUpdateRequest | dict | vendors, project_vendors, user_role_assignments | tier-scoped (admin/OA/PA); DEPRECATED |
| DELETE | /api/v3/vendors/{vendor_id} | vendors\routes.py:665 | req | VENDORS_MANAGE | n/a | 204 | vendors (soft-delete) | DEPRECATED |
| POST | /api/v3/vendors/{vendor_id}/restore | vendors\routes.py:699 | req | VENDORS_MANAGE | n/a | dict | vendors | DEPRECATED |
| GET | /api/v3/vendors/{vendor_id}/projects | vendors\routes.py:740 | req | VENDORS_READ | n/a | Collection | project_vendors, projects | DEPRECATED |
| GET | /api/v3/vendors/{vendor_id}/users | vendors\routes.py:787 | (proxy gate) | (delegated) | passthrough | passthrough | (user-mgmt) | **HTTP → PMIS-user-management** |

### resource_types — `app\api\v3\resource_types\routes.py`

Marked LEGACY (`resource_types\routes.py:1`).

| METHOD | PATH | HANDLER | AUTH | RBAC | NOTES |
|---|---|---|---|---|---|
| GET | /api/v3/resource_types | resource_types\routes.py:54 | req | RESOURCE_TYPES_READ | DEPRECATED → master/resource_types |
| POST | /api/v3/resource_types/create | resource_types\routes.py:74 | req | RESOURCE_TYPES_MANAGE | DEPRECATED |

### catalogs — `app\api\v3\catalogs\routes.py`

Marked LEGACY (`catalogs\routes.py:1`). Read-only.

| METHOD | PATH | HANDLER | AUTH | RBAC | NOTES |
|---|---|---|---|---|---|
| GET | /api/v3/divisions | catalogs\routes.py:56 | auth | (auth only) | DEPRECATED → /master/divisions |
| GET | /api/v3/project_status_transitions | catalogs\routes.py:124 | auth | (auth only) | DEPRECATED |
| GET | /api/v3/priorities | catalogs\routes.py:171 | auth | (auth only) | FE picker; NOT deprecated (kept) |

### roles — `app\api\v3\roles\routes.py` (prefix `/roles`)

Every endpoint stamps Deprecation headers per `_stamp(... successor="/api/v3/master/roles/...")` (`roles\routes.py:31-38`).

| METHOD | PATH | HANDLER | RBAC | NOTES |
|---|---|---|---|---|
| POST | /api/v3/roles/create | roles\routes.py:46 | ROLES_CREATE | DEPRECATED → master/roles/create |
| GET | /api/v3/roles | roles\routes.py:63 | ROLES_READ | DEPRECATED |
| GET | /api/v3/roles/{role_id} | roles\routes.py:81 | ROLES_READ | DEPRECATED |
| PATCH | /api/v3/roles/{role_id} | roles\routes.py:97 | ROLES_UPDATE | DEPRECATED |
| DELETE | /api/v3/roles/{role_id} | roles\routes.py:114 | ROLES_DELETE | DEPRECATED |
| GET | /api/v3/roles/{role_id}/permissions | roles\routes.py:149 | ROLES_READ | DEPRECATED |
| PUT | /api/v3/roles/{role_id}/permissions | roles\routes.py:187 | ROLES_UPDATE | DEPRECATED; admin role guarded |
| POST | /api/v3/roles/{role_id}/permissions/{code} | roles\routes.py:239 | ROLES_UPDATE | DEPRECATED |
| DELETE | /api/v3/roles/{role_id}/permissions/{code} | roles\routes.py:286 | ROLES_UPDATE | DEPRECATED |

### permissions — `app\api\v3\permissions\routes.py` (prefix `/permissions`)

| METHOD | PATH | HANDLER | RBAC | NOTES |
|---|---|---|---|---|
| GET | /api/v3/permissions | permissions\routes.py:60 | PERMISSIONS_READ | DEPRECATED → master/permissions |
| GET | /api/v3/permissions/{code} | permissions\routes.py:93 | PERMISSIONS_READ | DEPRECATED |
| POST | /api/v3/permissions | permissions\routes.py:118 | PERMISSIONS_MANAGE | DEPRECATED |
| PATCH | /api/v3/permissions/{code} | permissions\routes.py:151 | PERMISSIONS_MANAGE | DEPRECATED |
| DELETE | /api/v3/permissions/{code} | permissions\routes.py:181 | PERMISSIONS_MANAGE | DEPRECATED |

### master_data — `app\api\v3\master_data\routes.py` (prefix `/master`)

The consolidated CRUD surface introduced by doc 20. 72 decorators total (`@router.{get,post,patch,put,delete}` calls counted at `master_data\routes.py` — see line numbers below). All paths listed below are full paths.

**Divisions**

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/divisions | master_data\routes.py:193 |
| POST | /api/v3/master/divisions/create | :210 |
| PATCH | /api/v3/master/divisions/{code} | :241 |
| DELETE | /api/v3/master/divisions/{code} | :288 |
| POST | /api/v3/master/divisions/{code}/restore | :318 |

**Project status transitions**

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/project_status_transitions | :341 |
| POST | /api/v3/master/project_status_transitions/create | :359 |
| PATCH | /api/v3/master/project_status_transitions/{row_id} | :388 |
| DELETE | /api/v3/master/project_status_transitions/{row_id} | :411 |
| POST | /api/v3/master/project_status_transitions/{row_id}/restore | :429 |

**Resource types**

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/resource_types | :451 |
| POST | /api/v3/master/resource_types/create | :467 |
| PATCH | /api/v3/master/resource_types/{rt_id} | :488 |
| DELETE | /api/v3/master/resource_types/{rt_id} | :507 |
| POST | /api/v3/master/resource_types/{rt_id}/restore | :525 |

**Vendors** (delegates to legacy `vendors\routes.py` handlers — `master_data\routes.py:47-56`)

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/vendors | :565 |
| GET | /api/v3/master/vendors/{vendor_id} | :587 |
| POST | /api/v3/master/vendors/create | :600 |
| PATCH | /api/v3/master/vendors/{vendor_id} | :616 |
| DELETE | /api/v3/master/vendors/{vendor_id} | :632 |
| POST | /api/v3/master/vendors/{vendor_id}/restore | :647 |
| GET | /api/v3/master/vendors/{vendor_id}/projects | :662 |

**Roles** (delegates to legacy `roles\routes.py` — `master_data\routes.py:63-78`)

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/roles | :684 |
| GET | /api/v3/master/roles/{role_id} | :706 |
| POST | /api/v3/master/roles/create | :719 |
| PATCH | /api/v3/master/roles/{role_id} | :735 |
| DELETE | /api/v3/master/roles/{role_id} | :751 |
| GET | /api/v3/master/roles/{role_id}/permissions | :764 |
| PUT | /api/v3/master/roles/{role_id}/permissions | :777 |
| POST | /api/v3/master/roles/{role_id}/permissions/{code} | :795 |
| DELETE | /api/v3/master/roles/{role_id}/permissions/{code} | :811 |

**Permissions** (delegates — `master_data\routes.py:79-85`)

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/permissions | :831 |
| GET | /api/v3/master/permissions/by-module | :849 |
| GET | /api/v3/master/permissions/{code} | :904 |
| POST | /api/v3/master/permissions/create | :917 |
| PATCH | /api/v3/master/permissions/{code} | :933 |
| DELETE | /api/v3/master/permissions/{code} | :949 |

**Notification templates** (proxied to notification-service when flag on — `app\shared\notification_service_client.py:125-127`)

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/notification_templates | :996 |
| GET | /api/v3/master/notification_templates/{template_id} | :1034 |
| POST | /api/v3/master/notification_templates/create | :1053 |
| PATCH | /api/v3/master/notification_templates/{template_id} | :1103 |
| DELETE | /api/v3/master/notification_templates/{template_id} | :1180 |
| POST | /api/v3/master/notification_templates/{template_id}/restore | :1208 |

**Project categories** (lines 1443–1556)

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/project_categories | :1443 |
| GET | /api/v3/master/project_categories/{code} | :1462 |
| POST | /api/v3/master/project_categories/create | :1477 |
| PATCH | /api/v3/master/project_categories/{code} | :1502 |
| DELETE | /api/v3/master/project_categories/{code} | :1526 |
| POST | /api/v3/master/project_categories/{code}/restore | :1541 |

**Activity types** (1558–1669)

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/activity_types | :1558 |
| GET | /api/v3/master/activity_types/{code} | :1577 |
| POST | /api/v3/master/activity_types/create | :1592 |
| PATCH | /api/v3/master/activity_types/{code} | :1616 |
| DELETE | /api/v3/master/activity_types/{code} | :1639 |
| POST | /api/v3/master/activity_types/{code}/restore | :1654 |

**Milestone statuses** (1671–1784)

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/milestone_statuses | :1671 |
| GET | /api/v3/master/milestone_statuses/{code} | :1690 |
| POST | /api/v3/master/milestone_statuses/create | :1705 |
| PATCH | /api/v3/master/milestone_statuses/{code} | :1730 |
| DELETE | /api/v3/master/milestone_statuses/{code} | :1754 |
| POST | /api/v3/master/milestone_statuses/{code}/restore | :1769 |

**Activity statuses** (1786–1923)

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/activity_statuses | :1786 |
| GET | /api/v3/master/activity_statuses/{code} | :1805 |
| POST | /api/v3/master/activity_statuses/create | :1820 |
| PATCH | /api/v3/master/activity_statuses/{code} | :1845 |
| DELETE | /api/v3/master/activity_statuses/{code} | :1869 |
| POST | /api/v3/master/activity_statuses/{code}/restore | :1884 |

**Priorities** (1925–2063)

| METHOD | PATH | LINE |
|---|---|---|
| GET | /api/v3/master/priorities | :1925 |
| GET | /api/v3/master/priorities/{code} | :1946 |
| POST | /api/v3/master/priorities/create | :1961 |
| PATCH | /api/v3/master/priorities/{code} | :1995 |
| DELETE | /api/v3/master/priorities/{code} | :2027 |
| POST | /api/v3/master/priorities/{code}/restore | :2049 |

### comments — `app\api\v3\comments\routes.py`

Bulk-registered handlers for 4 target_kinds (milestone/activity/task/subtask) via `_KIND_BY_PATH` loop (`comments\routes.py:32-91`).

| METHOD | PATH (4 variants) | LINE | RBAC |
|---|---|---|---|
| POST | /api/v3/{milestones,activities,tasks,subtasks}/{target_id}/comments | comments\routes.py:71 (registered) | COMMENTS_CREATE |
| GET | /api/v3/{milestones,activities,tasks,subtasks}/{target_id}/comments | :85 | COMMENTS_READ |
| DELETE | /api/v3/comments/{comment_id} | :100 | auth-only (author or admin enforced in controller) |

### attachments — `app\api\v3\attachments\routes.py`

Doc-35 — attachments collapsed onto comments JSON column. 4 target_kinds.

| METHOD | PATH | LINE | RBAC |
|---|---|---|---|
| POST | /api/v3/{milestones,activities,tasks,subtasks}/{target_id}/attachments | attachments\routes.py:69 | ATTACHMENTS_CREATE |
| GET | /api/v3/{milestones,activities,tasks,subtasks}/{target_id}/attachments | :84 | COMMENTS_READ |
| DELETE | /api/v3/attachments/{attachment_id} | :109 | auth-only |

### dashboard — `app\api\v3\dashboard\routes.py` (prefix `/dashboard`, router-level `require_admin()`)

| METHOD | PATH | LINE | NOTES |
|---|---|---|---|
| GET | /api/v3/dashboard/summary | dashboard\routes.py:38 | admin-only (router dep) |
| GET | /api/v3/dashboard/projects | :58 | |
| GET | /api/v3/dashboard/projects/{project_uuid} | :90 | |
| GET | /api/v3/dashboard/projects/{project_uuid}/items | :111 | |
| GET | /api/v3/dashboard/organisations | :140 | |
| GET | /api/v3/dashboard/organisations/{vendor_id} | :156 | |

### project_members — `app\api\v3\project_members\routes.py`

OBSERVED: marked legacy/superseded by doc-41 role-assignments in the central router docstring (`app\api\router.py:98`).

| METHOD | PATH | LINE | RBAC |
|---|---|---|---|
| POST | /api/v3/projects/{project_uuid}/memberships/create | project_members\routes.py:46 | PROJECT_MEMBERS_ADD (proj-scoped) |
| GET | /api/v3/projects/{project_uuid}/memberships | :63 | PROJECT_MEMBERS_READ |
| PATCH | /api/v3/memberships/{membership_id} | :82 | PROJECT_MEMBERS_UPDATE |
| DELETE | /api/v3/memberships/{membership_id} | :104 | PROJECT_MEMBERS_DELETE |

NOTES: superseded by `/api/v3/projects/{id}/role-assignments`.

### work_packages — `app\api\v3\work_packages\routes.py` — **LEGACY (user-flagged for removal)**

| METHOD | PATH | LINE | RBAC |
|---|---|---|---|
| POST | /api/v3/projects/{project_uuid}/work_packages/create | work_packages\routes.py:45 | WORK_PACKAGES_CREATE |
| GET | /api/v3/projects/{project_uuid}/work_packages | :62 | WORK_PACKAGES_VIEW |
| GET | /api/v3/work_packages/{work_package_id} | :84 | WORK_PACKAGES_VIEW |
| PATCH | /api/v3/work_packages/{work_package_id} | :103 | WORK_PACKAGES_UPDATE |
| GET | /api/v3/work_packages/{work_package_id}/children | :123 | WORK_PACKAGES_VIEW |
| DELETE | /api/v3/work_packages/{work_package_id} | :142 | WORK_PACKAGES_DELETE |

NOTES: User-flagged legacy. Router docstring at `app\api\router.py:100` confirms: "less-used admin modules". Whole module slated for removal.

### work_package_types — `app\api\v3\work_package_types\routes.py` — **LEGACY**

| METHOD | PATH | LINE | RBAC |
|---|---|---|---|
| GET | /api/v3/work_package_types | work_package_types\routes.py:23 | WORK_PACKAGE_TYPES_VIEW |
| GET | /api/v3/work_package_types/{type_id} | :29 | WORK_PACKAGE_TYPES_VIEW |
| POST | /api/v3/work_package_types/create | :34 | WORK_PACKAGE_TYPES_MANAGE |
| PATCH | /api/v3/work_package_types/{type_id} | :39 | WORK_PACKAGE_TYPES_MANAGE |
| DELETE | /api/v3/work_package_types/{type_id} | :44 | WORK_PACKAGE_TYPES_MANAGE |

NOTES: Legacy companion to work_packages.

### meetings — `app\api\v3\meetings\routes.py` — **LEGACY (user-flagged for removal)**

Two routers: `projects_router(prefix="/projects")`, `meetings_router(prefix="/meetings")`.

| METHOD | PATH | LINE | RBAC |
|---|---|---|---|
| POST | /api/v3/projects/{project_uuid}/meetings/create | meetings\routes.py:46 | MEETINGS_CREATE |
| GET | /api/v3/projects/{project_uuid}/meetings | :64 | MEETINGS_VIEW |
| GET | /api/v3/meetings/{meeting_id} | :85 | MEETINGS_VIEW |
| PATCH | /api/v3/meetings/{meeting_id} | :105 | MEETINGS_UPDATE |
| DELETE | /api/v3/meetings/{meeting_id} | :127 | MEETINGS_DELETE |
| POST | /api/v3/meetings/{meeting_id}/participants/create | :148 | MEETINGS_UPDATE |
| GET | /api/v3/meetings/{meeting_id}/participants | :169 | MEETINGS_VIEW |
| DELETE | /api/v3/meetings/{meeting_id}/participants/{user_id} | :190 | MEETINGS_UPDATE |
| POST | /api/v3/meetings/{meeting_id}/agenda_items/create | :212 | MEETINGS_UPDATE |
| GET | /api/v3/meetings/{meeting_id}/agenda_items | :233 | MEETINGS_VIEW |
| GET | /api/v3/meetings/agenda_items/{agenda_item_id} | :253 | MEETINGS_VIEW |
| PATCH | /api/v3/meetings/agenda_items/{agenda_item_id} | :273 | MEETINGS_UPDATE |
| DELETE | /api/v3/meetings/agenda_items/{agenda_item_id} | :295 | MEETINGS_DELETE |

NOTES: User-flagged legacy. Whole module slated for removal.

### Top-level (app.main)

| METHOD | PATH | LINE | AUTH | NOTES |
|---|---|---|---|---|
| GET | /files/{storage_key:path} | main.py:188 | none | Dev fallback; mounted only if `FILE_SERVER_LOCAL_FALLBACK_ENABLED=true` |
| GET | /health | main.py:345 | none | Reports storage, notification, OTP-backdoor flags |
| GET | / | main.py:440 | none | API info |

### Route count summary

OBSERVED:
- Total `@*router.{get,post,patch,put,delete}` decorators counted: see file-by-file numbers above. INFERRED total: ~180 endpoints (users 23, projects 18, milestones 6, activities 6, tasks 6, subtasks 7, tree 1, vendors 8, resource_types 2, catalogs 3, roles 9, permissions 5, master_data 72, comments 3-paths × 2 + 1 = 9, attachments 9, dashboard 6, project_members 4, work_packages 6, work_package_types 5, meetings 13, app-level 3 = **~218 routes**). Treat the total as **[UNVERIFIED — count is the sum of the table rows above; if you need an exact route count run `app.routes` introspection]**.

---

## 4. Models (SQLAlchemy) (FULL)

OBSERVED file scan: `app\infrastructure\db\models\*.py` (41 model files). All declare `__tablename__` and use the shared `Base = DeclarativeBase` from `app\infrastructure\db\session.py:21`. Audited columns via grep on `Column(` patterns (see source citations below).

| TABLE | MODEL CLASS (file:line) | KEY COLUMNS | FKs | INDEXES (notable) | SOFT-DELETE? | TIMESTAMPS? | NOTES |
|---|---|---|---|---|---|---|---|
| users | UserModel `models\user.py:23` | id String(36) PK (UUID, doc 26 — `user.py:34`); user_code str unique; login/email unique; hashed_password; first/last_name; status; refresh_token_jti, previous_refresh_token_jti; vendor_id (FK); division/division_other; phone_number; org_role; two_factor_enabled; deleted_at/by | vendors.id (use_alter), users.id (self for deleted_by) | login, email, status, created_at, deleted_at, vendor_id (`user.py:126-131`) | YES (`deleted_at`/`deleted_by`) | YES | **OVERLAP with PMIS-user-management** (canonical owner) |
| projects | ProjectModel `models\project.py:23` | id String(36) UUID; project_code unique; name; status; owner/owner_other; category/category_other/category_other_reason; parent_id (self FK); start/end/actual_*; deleted_at/by | users.id (created_by/updated_by/deleted_by); projects.id (parent_id) | name, status, owner, category, start_date, end_date, deleted_at, project_code unique | YES | YES | OVERLAP with PMIS-project-management |
| project_audit_log**s** | ProjectAuditLogModel `project_audit_log.py:14` | id; project_id (FK); project_name/_status/owner snapshot; actor_id/login/code/role snapshot; action; before/after JSON; created_at | projects.id, users.id (actor) | project_id, actor_id, actor_login, actor_role, action, created_at | NO | created only | Doc 47 |
| milestones | MilestoneModel `milestone.py:16` | id UUID; project_id (FK); name; description; start/end/actual_*; position; status (default "not_completed"); priority; deleted_at | projects.id, users.id (cb/ub) | name, project_id, status, priority, deleted_at | YES | YES | |
| milestone_dependencies | MilestoneDependencyModel `milestone_dependency.py:24` | id UUID; source/target_milestone_id, project_id | milestones.id × 2, projects.id, users.id | partial unique on (source,target) WHERE deleted_at IS NULL | YES | created only | |
| milestone_vendors | MilestoneVendorModel `milestone_vendor.py:14` | milestone_id PK, vendor_id PK | milestones.id, vendors.id | composite PK | NO | created only | |
| milestone_statuses | MilestoneStatusModel `milestone_status.py:27` | id auto; code unique; label; is_builtin; is_terminal; active | none | code unique, active | NO | YES | doc 37 master catalog |
| activities | ActivityModel `activity.py:16` | id UUID; project_id (FK); milestone_id (FK); name; description; type (nullable post-doc-38); owner_division; concerned_division/concerned_divisions JSON; vendor_id; priority; start/end/actual_*; position; resource_mode/resource_count; status; deleted_at | projects.id, milestones.id, vendors.id, users.id, resource_types.id (indirect via activity_resources) | name, project_id, milestone_id, owner_division, concerned_division, vendor_id, priority, status, deleted_at | YES | YES | |
| activity_dependencies | ActivityDependencyModel `activity_dependency.py:40` | id UUID; source/target_activity_id; project_id | activities.id × 2, projects.id, users.id | partial unique | YES | created only | |
| activity_resources | ActivityResourceModel `activity_resource.py:16` | id UUID; activity_id; project_id; resource_name; onboard/offboard dates (planned + actual); designation; job_role; qualification; experience_years; type_of_resource_id (FK); division/_other | activities.id, projects.id, resource_types.id, users.id | activity_id, project_id | YES | YES | |
| activity_statuses | ActivityStatusModel `activity_status.py:26` | id auto; code unique; label; is_builtin/_terminal; active | none | code unique, active | NO | YES | doc 37 master catalog |
| activity_types | ActivityTypeModel `activity_type.py:26` | id auto; code unique; label; is_builtin; active | none | code unique, active | NO | YES | doc 37 master catalog |
| tasks | TaskModel `task.py:16` | id UUID; project_id; activity_id (FK); name; description; type; start/end/actual_*; position; resource_mode/count; status; priority; assigned_to (FK users); deleted_at | projects.id, activities.id, users.id × 3 | name, project_id, activity_id, status, priority, assigned_to, deleted_at | YES | YES | |
| task_dependencies | TaskDependencyModel `task_dependency.py:25` | id UUID; source/target_task_id; project_id | tasks.id × 2, projects.id, users.id | partial unique | YES | created only | |
| task_resources | TaskResourceModel `task_resource.py:16` | similar to activity_resources (task_id instead) | tasks.id, projects.id, users.id | task_id | YES | YES | |
| subtasks | SubtaskModel `subtask.py:30` | id UUID; project_id; task_id (FK, ROOT task even for nested); parent_subtask_id (FK self, doc 24); name; type; start/end/actual_*; position; resource_mode/count; status; priority; assigned_to; deleted_at | projects.id, tasks.id, subtasks.id (self for parent), users.id | name, project_id, task_id, parent_subtask_id, status, priority, assigned_to, deleted_at | YES | YES | Self-referential for nesting |
| subtask_dependencies | SubtaskDependencyModel `subtask_dependency.py:20` | id UUID; source/target_subtask_id; project_id | subtasks.id × 2, projects.id, users.id | partial unique | YES | created only | |
| subtask_resources | SubtaskResourceModel `subtask_resource.py:16` | similar | subtasks.id, projects.id, users.id | subtask_id | YES | YES | |
| comments | CommentModel `comment.py:40` | id UUID; target_kind (str); target_id (str — polymorphic to M/A/T/S/project); body (nullable); attachments JSON; author_user_id; deleted_at/by | users.id (author, deleted_by) | (target_kind, target_id), author_user_id, created_at, deleted_at | YES | YES | Doc 35 unified comments+attachments. Polymorphic by (target_kind, target_id) — no DB-level FK to target |
| vendors | VendorModel `vendor.py:31` | id UUID; vendor_code unique; name unique; description; active; email; contact_person; phone_number; deleted_at/by | users.id (deleted_by) | name unique, active, email, created_at, deleted_at | YES | YES | OVERLAP with master_data; legacy router still present |
| project_vendors | ProjectVendorModel `project_vendor.py:17` | project_id PK + vendor_id PK | projects.id, vendors.id | composite PK | NO | created only | M:N mapping |
| divisions | DivisionModel `division.py:41` | id auto; code unique; label; is_builtin; requires_other; active; email NOT NULL (doc 36); phone_number NOT NULL | none | code unique, active, email | NO | YES | Master catalog |
| project_categories | ProjectCategoryModel `project_category.py:26` | id auto; code unique; label; is_builtin; requires_other; active; description | none | code unique, active | NO | YES | Master catalog |
| project_status_transitions | ProjectStatusTransitionModel `project_status_transition.py:43` | id auto; from_status (nullable for "initial"); to_status; requires_admin; active; description | none | from_status, to_status, active | NO | YES | Catalog |
| priorities | PriorityModel `priority.py:20` | id UUID; code unique; name; description; position; active; is_builtin; deleted_at | none | code unique, active | YES (`deleted_at`) | YES | Catalog |
| resource_types | ResourceTypeModel `resource_type.py:19` | id UUID; code unique; name; active; deleted_at | none | code, active | YES | YES | Catalog |
| roles | RoleModel `role.py:21` | id Integer PK auto; name unique; description; builtin | none | name unique | NO | YES | OVERLAP with PMIS-user-management |
| permissions | PermissionModel `permission.py:25` | code String(128) PK; name; description; is_builtin | none | code (PK) | NO | YES | |
| role_permissions | RolePermissionModel `role_permission.py:14` | role_id PK + permission_code PK | roles.id, permissions.code | composite PK | NO | created only | |
| user_roles | UserRoleModel `user_role.py:14` | user_id PK + role_id PK | users.id, roles.id | composite PK | NO | created only | Legacy global-scope mapping; superseded by user_role_assignments |
| user_permissions | UserPermissionModel `user_permission.py:18` | user_id PK + permission_code PK | users.id, permissions.code | composite PK | NO | created only | Direct grants |
| user_role_assignments | UserRoleAssignmentModel `user_role_assignment.py:36` | id auto; user_id; role_id; organization_id (vendor.id); project_id; created_by | users.id, roles.id, vendors.id (org), projects.id | (user_id, role_id, organization_id, project_id) likely unique [UNVERIFIED] | NO | created only | Doc 41 scoped RBAC; replaces user_roles & project_members |
| revoked_tokens | RevokedTokenModel `revoked_token.py:26` | (jti-based) [UNVERIFIED — column list] | none | jti | n/a | created only | JWT blacklist |
| notification_log | NotificationLogModel `notification_log.py:22` | id auto; user_id (FK); channel; recipient; template_kind; payload JSON; status; error; created_at | users.id | channel, template_kind, status, created_at | NO | created only | |
| notification_templates | NotificationTemplateModel `notification_template.py:49` | id auto; template_kind; channel; subject; body; is_html; is_builtin; active; description | none | template_kind, channel, active | NO | YES | OVERLAP with PMIS-notification-service (canonical owner) |
| otp_codes | OtpCodeModel `otp_code.py:37` | id auto; user_id; channel; code_hash; ephemeral_token_hash; generated_at; expires_at; consumed_at; attempt_count; last_sent_at | users.id | ephemeral_token_hash, expires_at, consumed_at | n/a | created+ | OVERLAP with PMIS-user-management (login OTP) |
| password_reset_tokens | PasswordResetTokenModel `password_reset_token.py:32` | id auto; user_id; channel; token_hash unique; generated_at; expires_at; consumed_at | users.id | token_hash unique, expires_at | n/a | created+ | OVERLAP with PMIS-user-management |
| meetings | MeetingModel `meeting.py:14` | id Integer auto; project_id; title; description; scheduled_at; duration_minutes; location; created_by_id | projects.id, users.id | title, scheduled_at, created_by_id | NO | YES | **LEGACY (user-flagged)** |
| meeting_agenda_items | MeetingAgendaItemModel `meeting_agenda_item.py:14` | id Integer auto; meeting_id; project_id; title; position; work_package_id | meetings.id, projects.id, work_packages.id | meeting_id, position | NO | YES | **LEGACY (user-flagged)** |
| meeting_participants | MeetingParticipantModel `meeting_participant.py:14` | id Integer auto; meeting_id; user_id | meetings.id, users.id | meeting_id, user_id | NO | created only | **LEGACY (user-flagged)** |
| work_packages | WorkPackageModel `work_package.py:15` | id Integer auto; subject; description; project_id; parent_id (self); type_id; assignee_id; status; priority; done_ratio; start/end_date | projects.id, work_packages.id, work_package_types.id, users.id | subject, project_id, parent_id, type_id, status, priority | NO | YES | **LEGACY (user-flagged)**. No soft-delete. INFERRED: "old implementation of project modules" — predates milestones/activities/tasks hierarchy. |
| work_package_types | WorkPackageTypeModel `work_package_type.py:14` | id auto; name; internal_name unique; is_builtin; is_active; position | none | name, internal_name unique, position | NO | YES | **LEGACY (user-flagged)** |

NOTES on model legacy flags:
- `meetings`, `meeting_agenda_items`, `meeting_participants` → user-flagged LEGACY.
- `work_packages`, `work_package_types` → user-flagged LEGACY ("old implementation of project modules") — confirmed by router docstring `app\api\router.py:100` calling them "less-used admin modules" and the existence of the parallel milestones/activities/tasks/subtasks hierarchy.
- `user_roles` predates `user_role_assignments` (doc 41) and is itself partly legacy — `init_db` no longer seeds against it; new RBAC writes go to `user_role_assignments`. Still queried in `projects\routes.py:490-507` admin-tier scan.
- `project_members` (referenced in `app\api\router.py:98` as "superseded by doc-41 role-assignments") — but no `project_members` MODEL file exists in `app\infrastructure\db\models\`. INFERRED: the `project_members` route file uses `user_role_assignments` indirectly (per `baddc1146b85_unify_project_membership_into_user_*` migration name). [UNVERIFIED — confirm by reading `project_members\controller.py`].

---

## 5. Alembic migrations

OBSERVED migration list (`alembic\versions\*.py`, 41 files):

| FILENAME | REVISION | DOWN_REVISION | ONE-LINE SUMMARY | TYPE |
|---|---|---|---|---|
| 1272a77b9407_initial_schema.py | 1272a77b9407 | None | Initial schema | DDL |
| f9b8dd81f7dd_add_catalog_tables_and_category_other_.py | f9b8dd81f7dd | 1272a77b9407 | Add catalogs + project.category_other | DDL |
| eb3b19c7487c_add_actual_start_date_column_to_projects.py | eb3b19c7487c | f9b8dd81f7dd | projects.actual_start_date | DDL |
| 4825a33f9ed3_add_comments_and_attachments_tables.py | 4825a33f9ed3 | eb3b19c7487c | comments + attachments tables (pre-doc-35) | DDL |
| 7c4a91d8e3f0_add_vendor_soft_delete_columns.py | 7c4a91d8e3f0 | 4825a33f9ed3 | vendors soft-delete columns | DDL |
| b9e2f7c4a8d5_add_owner_other_column_to_projects.py | b9e2f7c4a8d5 | 7c4a91d8e3f0 | projects.owner_other | DDL |
| c3a8d5e1b962_add_divisions_table.py | c3a8d5e1b962 | b9e2f7c4a8d5 | divisions table | DDL |
| d4f1a8c5b6e7_add_vendor_contact_columns.py | d4f1a8c5b6e7 | c3a8d5e1b962 | vendors.email/contact_person/phone | DDL |
| c262a1b3e895_add_user_soft_delete_vendor_and_.py | c262a1b3e895 | d4f1a8c5b6e7 | users soft-delete + vendor + division | DDL |
| e7d2b3a4f981_add_refresh_token_grace_window_columns.py | e7d2b3a4f981 | c262a1b3e895 | refresh-token grace window | DDL |
| e7f4a8b9c1d2_rename_resource_type_ccm_to_ccn.py | e7f4a8b9c1d2 | c262a1b3e895 | rename resource_type code | data |
| eea66b52f947_merge_refresh_token_grace_window_with_.py | eea66b52f947 | (e7d2b3a4f981, e7f4a8b9c1d2) | **merge revision** | merge |
| f8a9c2d1e3b4_cleanup_test_data_in_resource_types_.py | f8a9c2d1e3b4 | eea66b52f947 | cleanup test data | data |
| b3c5d7e9f1a2_shorten_resource_type_display_names.py | b3c5d7e9f1a2 | f8a9c2d1e3b4 | resource_type display names | data |
| f3c8a7b2d491_drop_project_owners_table.py | f3c8a7b2d491 | eea66b52f947 | drop project_owners table | DDL |
| 4373b8cb0204_merge_master_data_drop_project_owners_.py | 4373b8cb0204 | (f3c8a7b2d491, b3c5d7e9f1a2) | **merge** master-data branches | merge |
| a1b2c3d4e5f6_add_milestone_dependencies_table.py | a1b2c3d4e5f6 | 4373b8cb0204 | milestone_dependencies | DDL |
| b2c3d4e5f6a7_db_driven_rbac.py | b2c3d4e5f6a7 | a1b2c3d4e5f6 | RBAC tables / DB-driven permissions | DDL |
| c4d9a1b3e201_doc22_drop_depends_add_position_unique.py | c4d9a1b3e201 | b2c3d4e5f6a7 | doc 22 — drop legacy `dependency` columns, add position UNIQUE | mixed |
| d8e1f3a4b502_doc23_add_users_phone_number.py | d8e1f3a4b502 | c4d9a1b3e201 | users.phone_number | DDL |
| e9f1a2b3c4d5_doc24_subtask_parent_subtask_id.py | e9f1a2b3c4d5 | d8e1f3a4b502 | subtasks.parent_subtask_id | DDL |
| f1a2b3c4d5e6_doc25_add_vendor_code.py | f1a2b3c4d5e6 | e9f1a2b3c4d5 | vendor_code | DDL |
| a2b3c4d5e6f7_doc25_add_user_code.py | a2b3c4d5e6f7 | f1a2b3c4d5e6 | user_code | DDL |
| b3c4d5e6f7a8_doc26_users_id_to_uuid.py | b3c4d5e6f7a8 | a2b3c4d5e6f7 | users.id → UUID | DDL (heavy) |
| d5e6f7a8b9c1_doc33_drop_versioning.py | d5e6f7a8b9c1 | b3c4d5e6f7a8 | doc 33 — drop project versioning (clone_of cols) | DDL |
| e6f7a8b9c1d2_doc33_change3_otp_password_reset_notifications.py | e6f7a8b9c1d2 | d5e6f7a8b9c1 | OTP + reset + notification_log/templates | DDL |
| f7a8b9c1d2e3_add_division_email_phone.py | f7a8b9c1d2e3 | e6f7a8b9c1d2 | divisions.email/phone | DDL |
| b8c9d0e1f2a3_doc35_unify_comments_attachments.py | b8c9d0e1f2a3 | f7a8b9c1d2e3 | unify comments+attachments (doc 35) | DDL |
| c2d4e7f9a1b3_doc36_notification_templates_division_required.py | c2d4e7f9a1b3 | b8c9d0e1f2a3 | notification_templates division required | DDL |
| d3e5f7a9b1c2_doc37_static_data_masters.py | d3e5f7a9b1c2 | c2d4e7f9a1b3 | doc 37 — project_categories, activity_types, ms/act statuses | DDL |
| e8d4f7a2b9c1_doc38_field_trim.py | e8d4f7a2b9c1 | d3e5f7a9b1c2 | doc 38 — field trim | DDL |
| f1e8d6a4b9c2_doc38_drop_activity_type_not_null.py | f1e8d6a4b9c2 | e8d4f7a2b9c1 | activities.type → nullable | DDL |
| a3f5b2c8d4e1_doc38_tasks_subtasks_status_and_type_nullable.py | a3f5b2c8d4e1 | f1e8d6a4b9c2 | tasks/subtasks status+type nullable | DDL |
| d2c4f8a9e1b3_doc39_activity_concerned_divisions.py | d2c4f8a9e1b3 | a3f5b2c8d4e1 | concerned_divisions JSON | DDL |
| e3f5b7a8c1d4_add_priorities_catalog.py | e3f5b7a8c1d4 | d2c4f8a9e1b3 | priorities catalog | DDL |
| d0c41a55145d_doc41_user_role_assignments.py | d0c41a55145d | e3f5b7a8c1d4 | user_role_assignments (scoped RBAC) | DDL |
| b5e7f2a8c9d3_priority_on_mts.py | b5e7f2a8c9d3 | d0c41a55145d | priority column on M/A/T/S | DDL |
| c8a3d4f6e9b2_assigned_to_on_ts.py | c8a3d4f6e9b2 | b5e7f2a8c9d3 | assigned_to on tasks+subtasks | DDL |
| d6b9c4f8a3e1_milestone_actual_dates.py | d6b9c4f8a3e1 | c8a3d4f6e9b2 | milestone actual dates | DDL |
| e9f1c3a5b704_doc45_users_org_role.py | e9f1c3a5b704 | d6b9c4f8a3e1 | users.org_role column | DDL |
| d2c4f1a9b8e7_uppercase_priority_codes.py | d2c4f1a9b8e7 | e9f1c3a5b704 | uppercase priority codes | data |
| b1d3e7a9c204_doc47_audit_log_enrichment.py | b1d3e7a9c204 | d2c4f1a9b8e7 | project_audit_logs enrichment | DDL |
| c3a8d1f7e542_doc47_audit_log_actor_code.py | c3a8d1f7e542 | b1d3e7a9c204 | project_audit_logs.actor_code | DDL |
| d4f9b2e8a317_backfill_actor_role.py | d4f9b2e8a317 | c3a8d1f7e542 | backfill actor_role | data |
| baddc1146b85_unify_project_membership_into_user_.py | baddc1146b85 | d4f9b2e8a317 | unify project_members into user_role_assignments | mixed |

OBSERVED:
- **Current head**: `baddc1146b85` (no migration has it as down_revision). INFERRED.
- **Multi-head merges**: `eea66b52f947` (merges `e7d2b3a4f981` + `e7f4a8b9c1d2`) and `4373b8cb0204` (merges `f3c8a7b2d491` + `b3c5d7e9f1a2`) — both explicit merge revisions. No orphan heads detected from the down_revision graph.
- **Orphans**: none observed.
- **Naming pattern**: most are `<docNN>_<feature>.py`; older ones (`1272a77b9407`, `eb3b19c7487c`, `f9b8dd81f7dd`) are pre-doc-naming. `baddc1146b85_unify_project_membership_into_user_.py` (head) trailing underscore + truncated description — naming-pattern outlier, consistent with auto-generated names.
- **Migration runner**: at boot, `init_db()` runs `alembic upgrade head` as a subprocess on Postgres (`app\infrastructure\db\session.py:209-280`); SQLite is `create_all` + ALTER auto-heal. `DATABASE_URL_MIGRATIONS` supported for elevated-DDL role (`alembic\env.py:35-36`, `config.py:74-81`).

---

## 6. Auth & RBAC implementation

OBSERVED:

- **JWT decode**: `app\core\security.py:89-107` (`decode_access_token`), using `python-jose` (`from jose import JWTError, jwt, ExpiredSignatureError` at `security.py:9`). Signed with `settings.SECRET_KEY` and `settings.ALGORITHM` (HS256 by default — `config.py:23`). Secret env var: `SECRET_KEY` (`config.py:19-22`).
- **JWT create**: `create_access_token` at `security.py:46-86`, `create_refresh_token` at `security.py:139-163`. Each token gets a fresh `jti = uuid4().hex` (`security.py:77`, `:149`).
- **AuthenticationMiddleware**: `app\core\middleware\auth.py:50-109`. Decodes the Bearer header, checks `jti` against `revoked_tokens`, validates UUID-shape of `user_id` claim (doc-27 pre-doc-26 guard at `auth.py:78-88`), and hydrates `request.state.user_permissions` + `request.state.is_admin` + `request.state.scoped_permissions` from `RbacRepository.effective_permissions_*` (`auth.py:124-144`).

- **Permission check pattern** — canonical implementation:
  - `require_permission(code)` — dependency factory at `app\core\middleware\rbac.py:42-60`. Reads `request.state.user_permissions` flat union. 401 if anonymous; 403 if perm missing.
  - `require_project_permission(code)` — at `app\core\middleware\rbac.py:373-398`. Resolves `project_id` via direct path-param or ancestor SQL lookup (`_resolve_project_id_from_path` at `:117-156`; `_ancestor_project_id` at `:159-251`). Checks scoped `("project", pid)`, then `("global", None)`, then any `("org", vendor_id)` of an owning vendor (`_has_project_scoped_permission` at `:343-370`).
  - `require_org_permission(code)` — at `app\core\middleware\rbac.py:401-430`.
  - `require_admin()` — at `:73-82`; reads `request.state.is_admin`.
  - `require_authenticated()` — at `:63-70`.

- **Permission name declarations**: `app\core\permissions.py:36-141` declares ~50 string codes as module-level constants. Example codes: `USERS_CREATE = "users:create"` (`permissions.py:36`), `PROJECTS_PUBLISH = "projects:publish"` (`:56`), `RBAC_ASSIGN = "rbac:assign"` (`:87`). Permissions are also declared per-module in `<feature>/permissions.py` files (e.g. `app\api\v3\users\permissions.py`, `projects\permissions.py`, etc. — used as the import target by route decorators).

- **RBAC tables and queries**:
  - Tables: `roles` (`role.py:21`), `permissions` (`permission.py:25`), `role_permissions` (`role_permission.py:14`), `user_roles` (`user_role.py:14` — legacy global), `user_permissions` (`user_permission.py:18` — direct grants), `user_role_assignments` (`user_role_assignment.py:36` — doc 41 scoped, columns `organization_id` and `project_id` define scope).
  - Repository: `app\infrastructure\db\repositories\rbac_repository.py` — imported at `auth.py:113-114, 133-134` and called for `effective_permissions_for_user`, `effective_permissions_by_scope`, `user_has_admin_role`, etc. [Specific method bodies not read; referenced by name].

- **Revoked-token table and check**:
  - Table: `revoked_tokens` (`revoked_token.py:26`, model `RevokedTokenModel`).
  - Check: `AuthenticationMiddleware._is_revoked(jti)` at `auth.py:111-121` opens a fresh `SessionLocal()`, calls `RevokedTokenRepository(db).is_revoked(jti)`, and short-circuits if revoked.

- **Auth/account flows** (endpoints + tables/services touched):
  - **Login**: POST `/api/v3/users/login` (`users\routes.py:88`). Touches `users` (lookup + 2FA check) and may insert `otp_codes` row + dispatch via notification client.
  - **Send-OTP**: POST `/api/v3/users/login/send-otp` (`:111`). Inserts/updates `otp_codes`; calls notification HTTP.
  - **Verify-OTP**: POST `/api/v3/users/login/verify-otp` (`:128`). Honors `UNIVERSAL_OTP_ENABLED` backdoor (`main.py:46-52`); on success rotates refresh token on `users` row.
  - **Forgot-password**: POST `/api/v3/users/forgot-password` (`:144`). Inserts `password_reset_tokens` row; calls notification HTTP. Anti-enumeration: always 200.
  - **Reset-password**: POST `/api/v3/users/reset-password` (`:159`). Consumes `password_reset_tokens`, updates `users.hashed_password`.
  - **Logout**: POST `/api/v3/users/logout` (`:177`). Inserts row into `revoked_tokens` (via blacklist); clears `users.refresh_token_jti`.
  - **Refresh**: POST `/api/v3/users/refresh` (`:68`). Validates against `users.refresh_token_jti` + grace window (`previous_refresh_token_jti` + `_valid_until` per `user.py:65-66`), rotates and reissues.

NOTES:
- **OVERLAP with PMIS-user-management**: the entire auth surface is mirrored in the sibling service. The monolith is the rollback path; when `USER_SERVICE_PROXY_ENABLED=true`, every `/api/v3/users/*` and `/api/v3/master/{roles,permissions}/*` and `/api/v3/role-grants/*` request is forwarded by the ASGI proxy middleware (`shared\user_service_client.py:239-249`).
- **UNIVERSAL_OTP backdoor** lives in the BE (config flag `UNIVERSAL_OTP_ENABLED` at `config.py:387-394`); the warning logs at `main.py:46-52`; the actual short-circuit lives in the `verify_otp` service [UNVERIFIED — line in `users\services\two_factor.py`].

---

## 7. Cross-service HTTP calls (outbound)

OBSERVED (grep `httpx\.|requests\.|aiohttp\.` across `app/`):

| FROM (file:line) | TO (URL pattern) | METHOD | PURPOSE | TIMEOUT/RETRY |
|---|---|---|---|---|
| app\main.py:386 | `${NOTIFICATION_SERVICE_URL}/api/v1/health` | GET | /health probe; notification reachability diagnostic | connect 2s, read/write/pool 3s; no retry |
| app\shared\notifications.py:339 | `${NOTIFICATION_SERVICE_URL}/api/v1/notifications/email/send` | POST | Send email OTP / reset link | connect 5s, read 15s; no retry |
| app\shared\notifications.py:354 | `${NOTIFICATION_SERVICE_URL}/api/v1/notifications/sms/send` | POST | Send SMS OTP / reset code | connect 5s, read 15s; no retry |
| app\shared\notification_service_client.py:69 (`_build_url`) | `${NOTIFICATION_SERVICE_URL}/api/v3/master/notification_templates/...` | passthrough | ASGI middleware forwards template CRUD; only when `NOTIFICATION_SERVICE_PROXY_ENABLED=true` | timeout from `NOTIFICATION_SERVICE_TIMEOUT_SECONDS` (default 10s); fail-closed 503; no retry |
| app\shared\user_service_client.py (`_build_url` + `_proxy_request_async`) | `${USER_SERVICE_URL}/api/v3/{users,master/roles,master/permissions,role-grants}/...` | passthrough | ASGI + explicit `proxy_or_503` callsites; forwards Authorization, content-type, X-Request-Id | connect 5s, read/write/pool = `USER_SERVICE_TIMEOUT_SECONDS` (default 10s); fail-closed 503; no retry |
| app\api\v3\projects\routes.py:1151 (POST /role-assignments) | (via `proxy_or_503`) `${USER_SERVICE_URL}/api/v3/projects/{id}/role-assignments` | POST | Project-scope role grant write | as above |
| app\api\v3\projects\routes.py:1168 (DELETE /role-assignments/{id}) | (via `proxy_or_503`) `${USER_SERVICE_URL}/api/v3/projects/{id}/role-assignments/{aid}` | DELETE | Revoke | as above |
| app\api\v3\vendors\routes.py:791 (GET /vendors/{id}/users) | (via `proxy_or_503`) `${USER_SERVICE_URL}/api/v3/vendors/{id}/users` | GET | List users mapped to a vendor (employees) | as above |

INFERRED:
- No retries anywhere — every call is a single attempt and falls back to a 503 (or error envelope passthrough from the upstream).
- Hardcoded URL paths are namespaced under `/api/v1/notifications/*` for the notification service (the only one with a different prefix), and `/api/v3/*` for everything else.
- No service-discovery layer — every URL is `settings.<SERVICE>_URL` + path. INFERRED: deployment topology is hardcoded via env.

---

## 8. Folder shape & nesting

OBSERVED tree of `app/` to depth 4:

```
app/
├── __init__.py
├── main.py
├── api/
│   ├── __init__.py
│   ├── router.py
│   └── v3/
│       ├── __init__.py
│       ├── _inline_attachments.py
│       ├── activities/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}
│       ├── attachments/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}
│       ├── catalogs/{__init__.py, routes.py}
│       ├── comments/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}
│       ├── dashboard/{__init__.py, controller.py, routes.py, schemas.py, services/}
│       ├── master_data/{__init__.py, routes.py, schemas.py}
│       ├── meetings/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}    [LEGACY]
│       ├── milestones/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}
│       ├── permissions/{__init__.py, routes.py, schemas.py}
│       ├── project_members/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}   [LEGACY]
│       ├── projects/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}
│       ├── resource_types/{__init__.py, routes.py}
│       ├── role_assignments/   [EMPTY DIR — see Notable findings]
│       ├── roles/{__init__.py, controller.py, permissions.py, routes.py, schemas.py}
│       ├── subtasks/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}
│       ├── tasks/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}
│       ├── tree/{__init__.py, routes.py, service.py}
│       ├── users/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, schemas/, services/}
│       ├── vendors/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services or assignments, user_assignments.py}
│       ├── work_package_types/{__init__.py, controller.py, permissions.py, routes.py, schemas.py}    [LEGACY]
│       └── work_packages/{__init__.py, controller.py, permissions.py, routes.py, schemas.py, services/}    [LEGACY]
├── core/
│   ├── __init__.py
│   ├── base_controller.py
│   ├── config.py
│   ├── dependencies.py
│   ├── errors.py
│   ├── middleware/{__init__.py, auth.py, logging.py, rbac.py}
│   ├── permissions.py
│   ├── project_lock.py
│   ├── rbac.py
│   ├── response.py
│   └── security.py
├── domain/
│   ├── __init__.py
│   ├── activities/, comments/, meetings/, milestones/, priorities/, project_members/, projects/,
│   ├── resource_types/, roles/, subtasks/, tasks/, users/, vendors/, work_package_types/, work_packages/
├── infrastructure/
│   ├── __init__.py
│   ├── db/{__init__.py, session.py, utc_datetime.py, models/, repositories/}
│   └── storage/
└── shared/
    ├── __init__.py
    ├── assignee.py, code_generators.py, comments_attachments_cascade.py, dashboard_derive.py,
    ├── date_rules.py, datetime.py, dep_block.py, dep_date_rules.py, file_signature.py, labels.py,
    ├── notification_service_client.py, notifications.py, otp.py, pagination.py, phone.py,
    ├── position_heal.py, project_code.py, service_result.py, static_catalog.py, user_service_client.py,
    └── utils.py
```

OBSERVED canonical per-resource subtree (cited fully): `app/api/v3/projects/` contains:
- `app\api\v3\projects\__init__.py`
- `app\api\v3\projects\controller.py`
- `app\api\v3\projects\permissions.py` — local permission code constants imported by `routes.py`
- `app\api\v3\projects\routes.py` — route definitions
- `app\api\v3\projects\schemas.py` — Pydantic models
- `app\api\v3\projects\services/` — multiple per-action files: `audit.py`, `close.py`, `create.py`, `delete.py`, `get.py`, `list.py`, `publish.py`, `save.py`, `transitions.py`, `update.py`, `upsert.py`

This shape is mirrored by activities, attachments, comments, dashboard, meetings, milestones, project_members, subtasks, tasks, users, vendors, work_packages. Smaller modules (catalogs, master_data, permissions, resource_types, roles, tree, work_package_types) skip `controller.py` and/or `services/`.

OBSERVED: **file count under app/**: 339 .py files (from `find /c/Programming/PMIS/PMIS-OpenProject/app -type f -name "*.py" | wc -l`).
[UNVERIFIED — total LOC]: PowerShell measure was denied; no exact LOC available. INFERRED rough order ≥ 30k LOC based on individual files like `master_data\routes.py` (2063 lines), `app\infrastructure\db\session.py` (1144+ lines), plus 41 model files and ~25 routes files each in the few-hundred to ~1000 line range.

Oddballs:
- `app\api\v3\role_assignments/` — **empty directory** (only `ls` shows no files). INFERRED: planned scaffold for the doc-41 scoped-RBAC migration that ended up not getting filed under its own folder; instead the writes were inlined into `projects/routes.py` (`projects\routes.py:1137-1168`) and `users\routes.py` (`users\routes.py:549-618`) — see comment at `shared\user_service_client.py:251-260`.
- `app\api\v3\users\schemas.py` AND `app\api\v3\users\schemas/` directory (both exist). The `schemas/` dir contains only `introspect.py`. INFERRED: someone began breaking up `schemas.py` into a subdirectory and stopped after one file — inconsistency hazard.
- `app\api\v3\vendors\user_assignments.py` — direct module (not in a subdir); imported by `vendors\routes.py:43-46`.
- `app\api\v3\_inline_attachments.py` — shared dispatcher module living at the `v3/` level, not inside a feature folder.
- Old/backup files at repo root: `deploy.sh-bak`, `docker-compose.yml-bak`, `docker-compose.override.yml.bak.2026-05-07`.
- `bench_pmis_local.db`, `pmis.db` — SQLite files committed (or at least present) at repo root.

---

## 9. Suspected legacy / dead code

OBSERVED (file-name patterns):
- No `*_old*.py`, `*_legacy*.py`, `*_v1*.py`, `*_deprecated*.py`, or `*.py.bak` files found under `app/` (Glob returned no matches).
- **Backup files at repo root** (NOT under `app/`):
  - `C:\Programming\PMIS\PMIS-OpenProject\deploy.sh-bak`
  - `C:\Programming\PMIS\PMIS-OpenProject\docker-compose.yml-bak`
  - `C:\Programming\PMIS\PMIS-OpenProject\docker-compose.override.yml.bak.2026-05-07`

### User-flagged LEGACY items — full enumeration

**`work_packages` (whole module)**
- Routes: `app\api\v3\work_packages\routes.py` (all 6 endpoints listed in §3) — included at `app\api\router.py:106-107`.
- Controller: `app\api\v3\work_packages\controller.py`
- Schemas: `app\api\v3\work_packages\schemas.py`
- Permissions: `app\api\v3\work_packages\permissions.py`
- Services: `app\api\v3\work_packages\services/`
- Domain: `app\domain\work_packages\`
- Model: `app\infrastructure\db\models\work_package.py` (table `work_packages`).
- Note: `work_package_types` is the companion — model `work_package_type.py` + router `work_package_types\routes.py` (5 endpoints, all listed in §3). Included at `app\api\router.py:108`.
- Per-row reference: `meeting_agenda_items.work_package_id` is a FK to `work_packages.id` (`meeting_agenda_item.py:25`), so the `meetings` legacy module also references `work_packages`. INFERRED: dropping both modules can be done together.

**`meetings` (whole module)**
- Routes: `app\api\v3\meetings\routes.py` (13 endpoints listed in §3) — included at `app\api\router.py:109-110`.
- Controller, schemas, permissions, services in `app\api\v3\meetings\`.
- Domain: `app\domain\meetings\`.
- Models: `meeting.py`, `meeting_agenda_item.py`, `meeting_participant.py` (3 tables: `meetings`, `meeting_agenda_items`, `meeting_participants`).

**"Old implementation of project modules"** — INFERRED candidates:
- The `work_packages` model + router IS the old implementation. The new hierarchy is `milestones → activities → tasks → subtasks`, each with its own table, model, router, controller, services, and dependency table. `WorkPackageModel.parent_id` is a self-FK (`work_package.py:24`) — the classic single-table flat hierarchy the new structure replaced.
- `project_members` module (`app\api\v3\project_members\` + `app\domain\project_members\`) — described as "superseded by doc-41 /api/v3/projects/{id}/role-assignments" in the central router docstring (`app\api\router.py:98`). The unify migration is `baddc1146b85_unify_project_membership_into_user_*` — the current head.
- Legacy roles / permissions / vendors / resource_types / catalogs routers — every endpoint already emits `Deprecation: true` (cited inline in §3); these are STILL ACTIVE but FE migration target is `/api/v3/master/*`.

**Other legacy / dead-ish signals**
- `BOOTSTRAP_ADMIN_*` env vars in `config.py:136-138` are still present, but `init_db()` no longer creates a bootstrap admin user per doc 42b (see comment block `session.py:634-641`). INFERRED: these env vars are dead — keep only `BOOTSTRAP_SUPERADMIN_*`.
- `users.previous_refresh_token_jti` + `_valid_until` (`user.py:65-66`) — only added because of an FE refresh-token race; INFERRED still in use and not legacy, but flagged as hotfix-style state.
- `UNIVERSAL_OTP_ENABLED` (`config.py:387-394`) — break-glass; not legacy but the docstring explicitly warns it MUST be off in prod.
- `app\api\v3\role_assignments/` — empty directory (see §8 Oddballs). Dead.
- `app\api\v3\users\schemas/introspect.py` — orphan single-file under `schemas/` next to `schemas.py`. Likely dead-or-pending.

**Unused routes / models** [UNVERIFIED unless otherwise noted]:
- `BOOTSTRAP_ADMIN_*` settings — unused at boot per the `session.py` comment, but the Pydantic settings field is still loaded.
- `RESOURCE_TYPES_READ` and `RESOURCE_TYPES_MANAGE` permission codes (`permissions.py:63-64`) — marked "deprecated, use master_data:*" in the descriptions; still referenced by `app\api\v3\resource_types\routes.py:51,70`.

**Commented-out blocks >10 lines**:
- `app\main.py:168-177` — large comment header for the doc-35 fallback route (description, not dead code).
- `app\infrastructure\db\session.py:282-619` — vast SQLite ALTER auto-heal block. Live code, but documents drift back to legacy on-disk DBs that pre-date specific migrations. INFERRED: at refactor time this entire block can be deleted in favour of "Postgres only, alembic only".
- [UNVERIFIED] No grep was run specifically for `>10 contiguous commented lines`. INFERRED: needs a targeted scan if you want a clean list.

---

## 10. Notable findings / risks

### Soft-delete inconsistencies
OBSERVED:
- The following tables have `deleted_at` (and usually `deleted_by`) and observe soft-delete: `users`, `projects`, `milestones`, `milestone_dependencies`, `activities`, `activity_dependencies`, `activity_resources`, `tasks`, `task_dependencies`, `task_resources`, `subtasks`, `subtask_dependencies`, `subtask_resources`, `comments`, `vendors`, `priorities`, `resource_types`.
- The following tables **do NOT** have soft-delete columns: `roles`, `role_permissions`, `user_roles`, `user_permissions`, `user_role_assignments`, `permissions`, `divisions`, `project_categories`, `project_status_transitions`, `activity_types`, `activity_statuses`, `milestone_statuses`, `notification_templates`, `notification_log`, `meetings`, `meeting_agenda_items`, `meeting_participants`, `work_packages`, `work_package_types`, `project_audit_logs`, `revoked_tokens`, `otp_codes`, `password_reset_tokens`, `milestone_vendors`, `project_vendors`.

NOTES:
- `work_packages` lacks soft-delete (`work_package.py`) — confirms it's a legacy contract; if you keep deleted history, the table would need a migration.
- `meetings` lacks soft-delete — dropping is feasible.
- `user_role_assignments` is the canonical RBAC mapping post-doc-41 but does NOT support soft-delete. Revocation = hard delete. May complicate audit. [UNVERIFIED — confirm in `rbac_repository.py`].

### Naming inconsistencies (snake_case vs camelCase)
OBSERVED (path-level):
- `/api/v3/users/login/send-otp`, `/login/verify-otp`, `/forgot-password`, `/reset-password` use **kebab-case** segments (users\routes.py:101, :118, :135, :151).
- `/api/v3/milestones/{milestone_id}/activities/create`, `/api/v3/projects/{project_uuid}/work_packages/create`, `/api/v3/projects/{project_uuid}/meetings/create` — **snake_case** action paths.
- `/api/v3/projects/{project_uuid}/role-assignments` — **kebab-case** in projects, but `/api/v3/projects/{project_uuid}/memberships/create` — **plain noun + /create** in project_members.
- Resource-list paths mix kebab and snake: `discussion-feed` (kebab, `projects\routes.py:944`), `audit-logs` (kebab, `:533`), `assignable-users` (kebab, `:389`), `role-assignments` (kebab, `:331`), vs. `memberships` (`project_members\routes.py:40`), `work_packages` (`work_packages\routes.py:25`), `work_package_types` (`work_package_types\routes.py:20`), `agenda_items` (`meetings\routes.py:206`), `notification_templates` (master_data — `:996`), `resource_types` (`:451`), `project_status_transitions` (`:341`), `project_categories` (`:1443`), `activity_types` (`:1558`), `milestone_statuses` (`:1671`), `activity_statuses` (`:1786`).
- The target architecture spec calls for `/<service>/<resource>/<action>` standardisation — this is a non-trivial number of paths to rewrite.

### Same-intent / different-path endpoint pairs
OBSERVED:

- **User-flagged pair**: `assign-roles` vs RBAC-filtered `/users`:
  - GET `/api/v3/projects/{project_uuid}/role-assignments` at `app\api\v3\projects\routes.py:343` — returns users grouped by the role they hold on this project (doc 44 round 8 mirror).
  - GET `/api/v3/projects/{project_uuid}/assignable-users` at `app\api\v3\projects\routes.py:404` — returns users that can be assigned a Task/Sub-Task on this project (union of (a) any user with a project-tier assignment on this project + (b) any user with `org_admin` on the project's owning vendor(s)).
  - GET `/api/v3/users` (`users\routes.py:229`) is also vendor-scoped for non-admin callers (per the round-7 filter mentioned in `permissions.py:323-326`). The FE's `DataContext` eagerly hits this on boot (per comment at `permissions.py:351-356`).
  - INFERRED: the FE currently has THREE overlapping ways to enumerate "users I can pick" — global `/users`, per-project `/assignable-users`, and per-project `/role-assignments`. Each enforces a different filter. Consolidation is needed.

- **Permission catalog**: `/api/v3/permissions` (legacy router, `permissions\routes.py`) AND `/api/v3/master/permissions` (master_data, delegating to the same handlers). Both still live; the legacy one stamps Deprecation.

- **Role catalog**: `/api/v3/roles/*` (legacy) AND `/api/v3/master/roles/*` (master_data delegating). Same situation.

- **Vendor catalog**: `/api/v3/vendors/*` (legacy) AND `/api/v3/master/vendors/*` (master_data delegating). Same situation.

- **Resource-type catalog**: `/api/v3/resource_types/*` (legacy) AND `/api/v3/master/resource_types/*`. Same.

- **Catalogs**: `/api/v3/divisions`, `/api/v3/project_status_transitions` (legacy read-only) AND `/api/v3/master/{divisions,project_status_transitions}/*` (full CRUD). `/api/v3/priorities` is its own non-deprecated picker that shadows `/api/v3/master/priorities`.

- **Comments + attachments**: every M/A/T/S has both `/comments` and `/attachments` URL pairs (`comments\routes.py:71`, `attachments\routes.py:69`), but post-doc-35 the underlying storage is the same table (`comments`). `DELETE /api/v3/attachments/{id}` is documented as "aliased to DELETE /comments/{id}" (`attachments\routes.py:99-107`). Refactor opportunity: collapse to one endpoint family.

- **Project members vs role-assignments**: `POST /api/v3/projects/{id}/memberships/create` (project_members\routes.py:40) vs `POST /api/v3/projects/{id}/role-assignments` (projects\routes.py:1137). Both write to `user_role_assignments` post-unification (per `baddc1146b85` migration). project_members is the legacy URL surface.

- **Logout vs revoke**: explicit POST `/api/v3/users/logout` (users\routes.py:177) writes to `revoked_tokens`; there's no separate "revoke a session" endpoint by jti. Logout is per-session.

### Data-migration risks
OBSERVED:
- `users.id` migrated from Integer to UUID String(36) at revision `b3c4d5e6f7a8_doc26_users_id_to_uuid.py`. The auth middleware still has a guard at `app\core\middleware\auth.py:78-88` to reject any pre-doc-26 integer-claim token — confirms a non-trivial migration cost was paid here and that JWTs minted before that revision must be reissued.
- `projects.id`, `milestones.id`, etc. are all UUID strings. FK from `users.id` etc. is `String(36)`. INFERRED: any service split that wants integer-PK semantics will need to redo this.
- `meeting_agenda_items.work_package_id` (`meeting_agenda_item.py:25`) is FK to `work_packages.id` — if `work_packages` is dropped, the meetings module must drop the column first (or be dropped at the same time).
- `notification_log.user_id` is FK to `users.id` (`notification_log.py:29`). If users move to a separate service, this FK becomes cross-service.
- `comments.target_id` is polymorphic — NOT a FK in the DB. INFERRED safer for splits.
- The SQLite ALTER auto-heal in `app\infrastructure\db\session.py:282-619` documents legacy schema drift back to pre-doc-25 / pre-doc-26 / pre-doc-33 shapes. Production likely doesn't hit this code (Postgres path), but the surface area of the heal block is large and indicates how much in-flight schema change has accumulated.

### Anything you want the human to decide before porting
1. **Status of `work_packages`, `work_package_types`, `meetings`, `meeting_*`** — confirm removal vs. archive-keep. The DB tables, the routers, the controllers, the domain entities, AND the `meeting_agenda_items.work_package_id` FK all need to be addressed.
2. **Status of `project_members` module** — appears to be effectively a thin wrapper over `user_role_assignments` since `baddc1146b85`. Remove or just rewire to user-mgmt?
3. **Catalog router fan-out**: `master_data\routes.py` is 2063 lines and registers 72 endpoints across 11 resource families (divisions, project_status_transitions, resource_types, vendors, roles, permissions, notification_templates, project_categories, activity_types, milestone_statuses, activity_statuses, priorities). Refactor decision: keep as one "masters" service, or split per family? Some entries delegate (vendors, roles, permissions); notification_templates delegate to the notification-service when the flag's on.
4. **Vendor scope is overloaded**: `vendor_id` doubles as `organization_id` in `user_role_assignments.organization_id` (`user_role_assignment.py:54`). The auth code at `app\core\middleware\rbac.py:295-313` walks `project_vendors` to apply org-scoped perms to projects. INFERRED: refactor must keep this org-vs-vendor identity.
5. **The notification HTTP backend hard-codes `/api/v1/notifications/...` paths** (`shared\notifications.py:339, :354`) while the proxy middleware uses `/api/v3/...` paths. Both targets are the SAME notification-service. Decide whether to converge on one prefix.
6. **No retries on outbound HTTP** (§7). Decide if the gateway/new services need retry middleware.
7. **`UNIVERSAL_OTP_ENABLED` break-glass** — surfaces on `/health`. Decide whether to keep as-is or drop entirely in the refactor.
8. **`/files/{storage_key:path}` is auth-free by design** (`main.py:188-201`, comment: "URLs embed an unguessable UUID prefix"). Decide if this is acceptable behind nginx or move to a CDN/file server.
9. **Auth secret rotation**: `SECRET_KEY` is a Pydantic field with a default `"your-secret-key-change-in-production-..."` (`config.py:19-22`). INFERRED: deployments override via env, but the in-code default is unsafe. Confirm prod deploys override.
10. **`init_db()` does heavy bootstrap work at every boot** (RBAC sync, vendor seed, division seed, transitions seed, notification template seed — `session.py:621-1118`). Decide which of these belong in the new services' own init paths vs. a one-time CI seed.
