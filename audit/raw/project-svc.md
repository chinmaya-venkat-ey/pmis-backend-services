# PMIS-project-management Audit

Audited path: `C:\Programming\PMIS\PMIS-project-management\`
All `path:line` references are relative to that root unless otherwise noted.

## 1. Tech & dependencies

OBSERVED (requirements.txt):
- Python 3.11-slim (Dockerfile:6)
- fastapi==0.115.6 (requirements.txt:1)
- uvicorn[standard]==0.32.1 (requirements.txt:2)
- sqlalchemy==2.0.36 (requirements.txt:3)
- psycopg2-binary==2.9.10 (requirements.txt:4)
- alembic==1.18.1 (requirements.txt:5)
- pydantic==2.10.3 (requirements.txt:6)
- pydantic-settings==2.7.0 (requirements.txt:7)
- email-validator==2.2.0 (requirements.txt:8)
- python-multipart==0.0.20 (requirements.txt:9)
- python-jose[cryptography]==3.3.0 (requirements.txt:10) -- JWT verify
- argon2-cffi==23.1.0 (requirements.txt:11)
- pytest==8.3.4 (requirements.txt:12)
- httpx==0.28.1 (requirements.txt:13) -- not used for outbound calls; FastAPI test client
- filetype==1.2.0 (requirements.txt:14) -- attachment MIME sniffing

## 2. Entry point & startup

- OBSERVED: ASGI app is `app.main:app` (app/main.py:39, Dockerfile:42).
- OBSERVED: Router mounted is `api_v3_router` with prefix `/api/v3` (app/api/router.py:38, app/main.py:106).
- OBSERVED: Middlewares (added in app/main.py:49-57; FastAPI applies in reverse order):
  - `CORSMiddleware` (app/main.py:49)
  - `LoggingMiddleware` (app/main.py:56, app/core/middleware/logging.py)
  - `AuthenticationMiddleware` (app/main.py:57, app/core/middleware/auth.py)
- OBSERVED: Exception handlers for `DomainError`, `RequestValidationError`, and generic `Exception` (app/main.py:62-101).
- OBSERVED: Lifespan handler runs `init_db()` on boot (app/main.py:29-36, app/infrastructure/db/session.py:40-72) which spawns `alembic upgrade head` as a subprocess.
- OBSERVED: Public paths (no JWT required): `/`, `/health`, `/docs`, `/redoc`, `/openapi.json`, `/files/{storage_key}` (app/main.py:193).
- OBSERVED: Optional fallback streaming route `GET /files/{storage_key:path}` mounted only when `FILE_SERVER_LOCAL_FALLBACK_ENABLED=true` (app/main.py:119-169).
- OBSERVED: Port 8003 (Dockerfile:38,42; docker-compose.yml:21). Confirmed.
- OBSERVED: DB schema = default `public` schema -- no schema name set in `create_engine` (app/infrastructure/db/session.py:21) or anywhere in the codebase (no `schema=` kwarg / no `__table_args__ = {"schema": ...}` in any model).

Env vars (app/core/config.py):
- `SECRET_KEY` (line 32) -- shared with user-service + monolith (auth depends on identical value).
- `ALGORITHM=HS256` (line 40)
- `ACCESS_TOKEN_EXPIRE_MINUTES=15` (line 41)
- `REFRESH_TOKEN_EXPIRE_DAYS=7` (line 42)
- `REFRESH_TOKEN_GRACE_SECONDS=120` (line 45)
- `SUBTASK_MAX_NESTING_DEPTH` (line 49)
- `DATABASE_URL` (line 52) -- same Postgres instance as monolith + user-service.
- `DATABASE_URL_MIGRATIONS` (line 56) -- optional elevated-priv URL for `alembic upgrade head`.
- `MIGRATIONS_AUTORUN=True`, `MIGRATIONS_REQUIRED=True` (lines 65-66)
- `CORS_ORIGINS=["*"]` (line 69)
- `DEFAULT_PAGE_SIZE=20`, `MAX_PAGE_SIZE=100` (lines 70-71)
- `ATTACHMENTS_STORAGE_BASE_PATH` (line 74)
- `ATTACHMENTS_NFS_SERVER` / `ATTACHMENTS_NFS_EXPORT` (lines 82,86) -- informational
- `ATTACHMENTS_MAX_BYTES=26214400` (line 90)
- `ATTACHMENTS_ALLOWED_EXTENSIONS=pdf,docx,xlsx,txt,csv,jpg,jpeg,png,heic,mp4,webm,mov` (line 95)
- `ATTACHMENTS_SUBDIR_STRATEGY="year_month"` (line 98)
- `ATTACHMENTS_RETENTION_DAYS=90` (line 99)
- `ATTACHMENTS_ON_UNAVAILABLE="fail"` (line 100)
- `FILE_SERVER_PUBLIC_BASE_URL` (line 103), `FILE_SERVER_LOCAL_FALLBACK_ENABLED=True` (line 111), `FILE_SERVER_BASE_URL` (line 118), `FILE_SERVER_AUTH_TOKEN` (line 125)
- `FRONTEND_BASE_URL` (line 131)
- `DIVISION_DEFAULT_EMAIL` (line 137), `DIVISION_DEFAULT_PHONE` (line 141)

NOT present here (canonically on user-service): OTP / 2FA / notification / bootstrap-admin (app/core/config.py:146-147).

## 3. Route inventory

All paths below are prefixed `/api/v3` from the central router (app/api/router.py:38). LEGACY rules: every route in `vendors/`, `catalogs/`, `resource_types/` is wire-deprecated (stamps `Deprecation: true`) by `master_data/` -- marked SUSPECTED-LEGACY here because target shape will be flat (and master_data is the successor wire surface). Project-domain routes that the FE still hits via the legacy paths remain CURRENT.

| METHOD | PATH | HANDLER (file:line) | AUTH | RBAC | DB TABLES | EXTERNAL HTTP | LEGACY? | NOTES |
|---|---|---|---|---|---|---|---|---|
| POST   | /api/v3/projects/create                                    | app/api/v3/projects/routes.py:144 | JWT | PROJECTS_CREATE        | projects, comments, project_vendors | none | N | dual JSON/multipart with files |
| PUT    | /api/v3/projects/{project_uuid}                            | app/api/v3/projects/routes.py:174 | JWT | PROJECTS_CREATE        | projects | none | N | idempotent upsert |
| GET    | /api/v3/projects                                           | app/api/v3/projects/routes.py:193 | JWT | PROJECTS_READ          | projects | none | N | live only |
| GET    | /api/v3/projects/all                                       | app/api/v3/projects/routes.py:219 | JWT | PROJECTS_READ          | projects | none | N | includes deleted |
| GET    | /api/v3/projects/{project_uuid}                            | app/api/v3/projects/routes.py:239 | JWT | PROJECTS_READ          | projects | none | N | |
| PATCH  | /api/v3/projects/{project_uuid}                            | app/api/v3/projects/routes.py:252 | JWT | PROJECTS_UPDATE        | projects | none | N | |
| DELETE | /api/v3/projects/{project_uuid}                            | app/api/v3/projects/routes.py:266 | JWT | PROJECTS_DELETE_ALL    | projects | none | N | soft delete |
| POST   | /api/v3/projects/{project_uuid}/save                       | app/api/v3/projects/routes.py:285 | JWT | PROJECTS_UPDATE        | projects | none | N | new -> draft transition |
| POST   | /api/v3/projects/{project_uuid}/publish                    | app/api/v3/projects/routes.py:298 | JWT | PROJECTS_PUBLISH       | projects | none | N | |
| POST   | /api/v3/projects/{project_uuid}/close                      | app/api/v3/projects/routes.py:311 | JWT | PROJECTS_CLOSE         | projects | none | N | |
| GET    | /api/v3/projects/{project_uuid}/assignable-users           | app/api/v3/projects/routes.py:341 | JWT | PROJECT_MEMBERS_READ   | users, user_role_assignments, roles, project_vendors | none | N | reads user-service tables -- shared DB |
| GET    | /api/v3/projects/{project_uuid}/audit-logs                 | app/api/v3/projects/routes.py:480 | JWT | PROJECTS_READ          | project_audit_logs, projects, milestone_dependencies, activity_dependencies, task_dependencies, subtask_dependencies | none | N | doc 47 |
| GET    | /api/v3/projects/{project_uuid}/attachments                | app/api/v3/projects/routes.py:721 | JWT | PROJECTS_READ          | comments, projects | none | N | reads comments table |
| POST   | /api/v3/projects/{project_uuid}/attachments                | app/api/v3/projects/routes.py:787 | JWT | COMMENTS_CREATE        | comments, projects | none | N | multipart |
| GET    | /api/v3/projects/{project_uuid}/discussion-feed            | app/api/v3/projects/routes.py:891 | JWT | PROJECTS_READ          | comments, projects, milestones, activities, tasks, subtasks | none | N | |
| GET    | /api/v3/projects/{project_uuid}/tree                       | app/api/v3/tree/routes.py:29     | JWT | PROJECTS_READ          | projects, milestones, activities, tasks, subtasks, ...resources | none | N | full hierarchy |
| POST   | /api/v3/projects/{project_uuid}/milestones/create          | app/api/v3/milestones/routes.py:135  | JWT | MILESTONES_CREATE | milestones, comments | none | N | dual JSON/multipart |
| GET    | /api/v3/projects/{project_uuid}/milestones                 | app/api/v3/milestones/routes.py:167  | JWT | MILESTONES_READ   | milestones | none | N | |
| GET    | /api/v3/milestones/{milestone_id}                          | app/api/v3/milestones/routes.py:187  | JWT | MILESTONES_READ   | milestones | none | N | |
| PATCH  | /api/v3/milestones/{milestone_id}                          | app/api/v3/milestones/routes.py:200  | JWT | MILESTONES_UPDATE | milestones | none | N | |
| DELETE | /api/v3/milestones/{milestone_id}                          | app/api/v3/milestones/routes.py:214  | JWT | MILESTONES_DELETE | milestones, activities, tasks, subtasks | none | N | cascade soft-delete |
| POST   | /api/v3/milestones/{milestone_id}/restore                  | app/api/v3/milestones/routes.py:227  | JWT | MILESTONES_RESTORE | milestones | none | N | |
| POST   | /api/v3/milestones/{milestone_id}/activities/create        | app/api/v3/activities/routes.py:106 | JWT | ACTIVITIES_CREATE | activities, comments | none | N | dual mode |
| GET    | /api/v3/milestones/{milestone_id}/activities               | app/api/v3/activities/routes.py:126 | JWT | ACTIVITIES_READ   | activities | none | N | |
| GET    | /api/v3/activities/{activity_id}                           | app/api/v3/activities/routes.py:144 | JWT | ACTIVITIES_READ   | activities | none | N | |
| PATCH  | /api/v3/activities/{activity_id}                           | app/api/v3/activities/routes.py:153 | JWT | ACTIVITIES_UPDATE | activities | none | N | |
| DELETE | /api/v3/activities/{activity_id}                           | app/api/v3/activities/routes.py:165 | JWT | ACTIVITIES_DELETE | activities, tasks, subtasks | none | N | cascade |
| POST   | /api/v3/activities/{activity_id}/restore                   | app/api/v3/activities/routes.py:174 | JWT | ACTIVITIES_RESTORE | activities | none | N | |
| POST   | /api/v3/activities/{activity_id}/tasks/create              | app/api/v3/tasks/routes.py:85  | JWT | TASKS_CREATE  | tasks, task_resources, comments | none | N | |
| GET    | /api/v3/activities/{activity_id}/tasks                     | app/api/v3/tasks/routes.py:105 | JWT | TASKS_READ    | tasks | none | N | |
| GET    | /api/v3/tasks/{task_id}                                    | app/api/v3/tasks/routes.py:123 | JWT | TASKS_READ    | tasks | none | N | |
| PATCH  | /api/v3/tasks/{task_id}                                    | app/api/v3/tasks/routes.py:132 | JWT | TASKS_UPDATE  | tasks, task_resources | none | N | type-transition aware |
| DELETE | /api/v3/tasks/{task_id}                                    | app/api/v3/tasks/routes.py:141 | JWT | TASKS_DELETE  | tasks, subtasks | none | N | cascade |
| POST   | /api/v3/tasks/{task_id}/restore                            | app/api/v3/tasks/routes.py:150 | JWT | TASKS_RESTORE | tasks | none | N | |
| POST   | /api/v3/tasks/{task_id}/subtasks/create                    | app/api/v3/subtasks/routes.py:79  | JWT | SUBTASKS_CREATE  | subtasks, subtask_resources, comments | none | N | |
| GET    | /api/v3/tasks/{task_id}/subtasks                           | app/api/v3/subtasks/routes.py:99  | JWT | SUBTASKS_READ    | subtasks | none | N | |
| POST   | /api/v3/subtasks/{parent_subtask_id}/subtasks/create       | app/api/v3/subtasks/routes.py:125 | JWT | SUBTASKS_CREATE  | subtasks | none | N | nested |
| GET    | /api/v3/subtasks/{subtask_id}                              | app/api/v3/subtasks/routes.py:147 | JWT | SUBTASKS_READ    | subtasks | none | N | |
| PATCH  | /api/v3/subtasks/{subtask_id}                              | app/api/v3/subtasks/routes.py:156 | JWT | SUBTASKS_UPDATE  | subtasks, subtask_resources | none | N | |
| DELETE | /api/v3/subtasks/{subtask_id}                              | app/api/v3/subtasks/routes.py:165 | JWT | SUBTASKS_DELETE  | subtasks | none | N | |
| POST   | /api/v3/subtasks/{subtask_id}/restore                      | app/api/v3/subtasks/routes.py:174 | JWT | SUBTASKS_RESTORE | subtasks | none | N | |
| POST   | /api/v3/{milestones\|activities\|tasks\|subtasks}/{target_id}/comments | app/api/v3/comments/routes.py:71-84 | JWT | COMMENTS_CREATE | comments | none | N | 4 routes, factory |
| GET    | /api/v3/{milestones\|activities\|tasks\|subtasks}/{target_id}/comments | app/api/v3/comments/routes.py:85-91 | JWT | COMMENTS_READ   | comments | none | N | 4 routes, factory |
| DELETE | /api/v3/comments/{comment_id}                              | app/api/v3/comments/routes.py:101 | JWT | authenticated | comments | none | N | author/admin |
| POST   | /api/v3/{milestones\|activities\|tasks\|subtasks}/{target_id}/attachments | app/api/v3/attachments/routes.py:69-83 | JWT | ATTACHMENTS_CREATE | comments | none | N | 4 routes |
| GET    | /api/v3/{milestones\|activities\|tasks\|subtasks}/{target_id}/attachments | app/api/v3/attachments/routes.py:84-94 | JWT | COMMENTS_READ | comments | none | N | 4 routes |
| DELETE | /api/v3/attachments/{attachment_id}                        | app/api/v3/attachments/routes.py:109 | JWT | authenticated | comments | none | N | doc 35 alias |
| GET    | /api/v3/divisions                                          | app/api/v3/catalogs/routes.py:56  | JWT | authenticated         | divisions | none | Y (deprecated, see master_data) | stamps Deprecation header |
| GET    | /api/v3/project_status_transitions                         | app/api/v3/catalogs/routes.py:124 | JWT | authenticated         | project_status_transitions | none | Y (deprecated) | |
| GET    | /api/v3/priorities                                         | app/api/v3/catalogs/routes.py:171 | JWT | authenticated         | priorities | none | N | FE picker; doc 41 |
| GET    | /api/v3/resource_types                                     | app/api/v3/resource_types/routes.py:54 | JWT | RESOURCE_TYPES_READ | resource_types | none | Y (deprecated) | |
| POST   | /api/v3/resource_types/create                              | app/api/v3/resource_types/routes.py:74 | JWT | RESOURCE_TYPES_MANAGE | resource_types | none | Y (deprecated) | |
| GET    | /api/v3/vendors                                            | app/api/v3/vendors/routes.py:242 | JWT | VENDORS_READ | vendors, project_vendors, projects | none | Y (deprecated) | |
| GET    | /api/v3/vendors/{vendor_id}                                | app/api/v3/vendors/routes.py:289 | JWT | VENDORS_READ | vendors, project_vendors, projects, users, user_role_assignments, roles | none | Y (deprecated) | scope check |
| POST   | /api/v3/vendors/create                                     | app/api/v3/vendors/routes.py:372 | JWT | VENDORS_MANAGE | vendors, project_vendors, user_role_assignments | none | Y (deprecated) | |
| PATCH  | /api/v3/vendors/{vendor_id}                                | app/api/v3/vendors/routes.py:468 | JWT | body-shape gate (VENDORS_MANAGE / rbac:assign) | vendors, project_vendors, user_role_assignments, roles, users | none | Y (deprecated) | |
| DELETE | /api/v3/vendors/{vendor_id}                                | app/api/v3/vendors/routes.py:640 | JWT | VENDORS_MANAGE | vendors | none | Y (deprecated) | |
| POST   | /api/v3/vendors/{vendor_id}/restore                        | app/api/v3/vendors/routes.py:674 | JWT | VENDORS_MANAGE | vendors | none | Y (deprecated) | |
| GET    | /api/v3/vendors/{vendor_id}/projects                       | app/api/v3/vendors/routes.py:715 | JWT | VENDORS_READ | vendors, project_vendors, projects | none | Y (deprecated) | |
| GET    | /api/v3/master/divisions                                   | app/api/v3/master_data/routes.py:160  | JWT | MASTER_DATA_VIEW   | divisions | none | N | |
| POST   | /api/v3/master/divisions/create                            | app/api/v3/master_data/routes.py:177  | JWT | MASTER_DATA_MANAGE | divisions | none | N | |
| PATCH  | /api/v3/master/divisions/{code}                            | app/api/v3/master_data/routes.py:221  | JWT | MASTER_DATA_MANAGE | divisions | none | N | |
| DELETE | /api/v3/master/divisions/{code}                            | app/api/v3/master_data/routes.py:266  | JWT | MASTER_DATA_MANAGE | divisions | none | N | |
| POST   | /api/v3/master/divisions/{code}/restore                    | app/api/v3/master_data/routes.py:289  | JWT | MASTER_DATA_MANAGE | divisions | none | N | |
| GET    | /api/v3/master/project_status_transitions                  | app/api/v3/master_data/routes.py:312  | JWT | MASTER_DATA_VIEW   | project_status_transitions | none | N | |
| POST   | /api/v3/master/project_status_transitions/create           | app/api/v3/master_data/routes.py:331  | JWT | MASTER_DATA_MANAGE | project_status_transitions | none | N | |
| PATCH  | /api/v3/master/project_status_transitions/{row_id}         | app/api/v3/master_data/routes.py:359  | JWT | MASTER_DATA_MANAGE | project_status_transitions | none | N | |
| DELETE | /api/v3/master/project_status_transitions/{row_id}         | app/api/v3/master_data/routes.py:382  | JWT | MASTER_DATA_MANAGE | project_status_transitions | none | N | |
| POST   | /api/v3/master/project_status_transitions/{row_id}/restore | app/api/v3/master_data/routes.py:400  | JWT | MASTER_DATA_MANAGE | project_status_transitions | none | N | |
| GET    | /api/v3/master/resource_types                              | app/api/v3/master_data/routes.py:422  | JWT | MASTER_DATA_VIEW   | resource_types | none | N | |
| POST   | /api/v3/master/resource_types/create                       | app/api/v3/master_data/routes.py:439  | JWT | MASTER_DATA_MANAGE | resource_types | none | N | |
| PATCH  | /api/v3/master/resource_types/{rt_id}                      | app/api/v3/master_data/routes.py:459  | JWT | MASTER_DATA_MANAGE | resource_types | none | N | |
| DELETE | /api/v3/master/resource_types/{rt_id}                      | app/api/v3/master_data/routes.py:478  | JWT | MASTER_DATA_MANAGE | resource_types | none | N | |
| POST   | /api/v3/master/resource_types/{rt_id}/restore              | app/api/v3/master_data/routes.py:496  | JWT | MASTER_DATA_MANAGE | resource_types | none | N | |
| GET    | /api/v3/master/vendors                                     | app/api/v3/master_data/routes.py:536  | JWT | MASTER_DATA_VIEW   | (delegate to /api/v3/vendors) | none | N | strips Deprecation |
| GET    | /api/v3/master/vendors/{vendor_id}                         | app/api/v3/master_data/routes.py:558  | JWT | MASTER_DATA_VIEW   | (delegate) | none | N | |
| POST   | /api/v3/master/vendors/create                              | app/api/v3/master_data/routes.py:572  | JWT | MASTER_DATA_MANAGE | (delegate) | none | N | |
| PATCH  | /api/v3/master/vendors/{vendor_id}                         | app/api/v3/master_data/routes.py:587  | JWT | MASTER_DATA_MANAGE | (delegate) | none | N | |
| DELETE | /api/v3/master/vendors/{vendor_id}                         | app/api/v3/master_data/routes.py:603  | JWT | MASTER_DATA_MANAGE | (delegate) | none | N | |
| POST   | /api/v3/master/vendors/{vendor_id}/restore                 | app/api/v3/master_data/routes.py:618  | JWT | MASTER_DATA_MANAGE | (delegate) | none | N | |
| GET    | /api/v3/master/vendors/{vendor_id}/projects                | app/api/v3/master_data/routes.py:633  | JWT | MASTER_DATA_VIEW   | (delegate) | none | N | |
| GET    | /api/v3/master/project_categories                          | app/api/v3/master_data/routes.py:846  | JWT | MASTER_DATA_VIEW   | project_categories | none | N | |
| GET    | /api/v3/master/project_categories/{code}                   | app/api/v3/master_data/routes.py:865  | JWT | MASTER_DATA_VIEW   | project_categories | none | N | |
| POST   | /api/v3/master/project_categories/create                   | app/api/v3/master_data/routes.py:881  | JWT | MASTER_DATA_MANAGE | project_categories | none | N | |
| PATCH  | /api/v3/master/project_categories/{code}                   | app/api/v3/master_data/routes.py:905  | JWT | MASTER_DATA_MANAGE | project_categories | none | N | |
| DELETE | /api/v3/master/project_categories/{code}                   | app/api/v3/master_data/routes.py:929  | JWT | MASTER_DATA_MANAGE | project_categories | none | N | |
| POST   | /api/v3/master/project_categories/{code}/restore           | app/api/v3/master_data/routes.py:944  | JWT | MASTER_DATA_MANAGE | project_categories | none | N | |
| GET    | /api/v3/master/activity_types                              | app/api/v3/master_data/routes.py:961  | JWT | MASTER_DATA_VIEW   | activity_types | none | N | |
| GET    | /api/v3/master/activity_types/{code}                       | app/api/v3/master_data/routes.py:980  | JWT | MASTER_DATA_VIEW   | activity_types | none | N | |
| POST   | /api/v3/master/activity_types/create                       | app/api/v3/master_data/routes.py:996  | JWT | MASTER_DATA_MANAGE | activity_types | none | N | |
| PATCH  | /api/v3/master/activity_types/{code}                       | app/api/v3/master_data/routes.py:1019 | JWT | MASTER_DATA_MANAGE | activity_types | none | N | |
| DELETE | /api/v3/master/activity_types/{code}                       | app/api/v3/master_data/routes.py:1042 | JWT | MASTER_DATA_MANAGE | activity_types | none | N | |
| POST   | /api/v3/master/activity_types/{code}/restore               | app/api/v3/master_data/routes.py:1057 | JWT | MASTER_DATA_MANAGE | activity_types | none | N | |
| GET    | /api/v3/master/milestone_statuses                          | app/api/v3/master_data/routes.py:1074 | JWT | MASTER_DATA_VIEW   | milestone_statuses | none | N | |
| GET    | /api/v3/master/milestone_statuses/{code}                   | app/api/v3/master_data/routes.py:1093 | JWT | MASTER_DATA_VIEW   | milestone_statuses | none | N | |
| POST   | /api/v3/master/milestone_statuses/create                   | app/api/v3/master_data/routes.py:1109 | JWT | MASTER_DATA_MANAGE | milestone_statuses | none | N | |
| PATCH  | /api/v3/master/milestone_statuses/{code}                   | app/api/v3/master_data/routes.py:1133 | JWT | MASTER_DATA_MANAGE | milestone_statuses | none | N | |
| DELETE | /api/v3/master/milestone_statuses/{code}                   | app/api/v3/master_data/routes.py:1157 | JWT | MASTER_DATA_MANAGE | milestone_statuses | none | N | |
| POST   | /api/v3/master/milestone_statuses/{code}/restore           | app/api/v3/master_data/routes.py:1172 | JWT | MASTER_DATA_MANAGE | milestone_statuses | none | N | |
| GET    | /api/v3/master/activity_statuses                           | app/api/v3/master_data/routes.py:1189 | JWT | MASTER_DATA_VIEW   | activity_statuses | none | N | |
| GET    | /api/v3/master/activity_statuses/{code}                    | app/api/v3/master_data/routes.py:1208 | JWT | MASTER_DATA_VIEW   | activity_statuses | none | N | |
| POST   | /api/v3/master/activity_statuses/create                    | app/api/v3/master_data/routes.py:1224 | JWT | MASTER_DATA_MANAGE | activity_statuses | none | N | |
| PATCH  | /api/v3/master/activity_statuses/{code}                    | app/api/v3/master_data/routes.py:1248 | JWT | MASTER_DATA_MANAGE | activity_statuses | none | N | |
| DELETE | /api/v3/master/activity_statuses/{code}                    | app/api/v3/master_data/routes.py:1272 | JWT | MASTER_DATA_MANAGE | activity_statuses | none | N | |
| POST   | /api/v3/master/activity_statuses/{code}/restore            | app/api/v3/master_data/routes.py:1287 | JWT | MASTER_DATA_MANAGE | activity_statuses | none | N | |
| GET    | /api/v3/master/priorities                                  | app/api/v3/master_data/routes.py:1328 | JWT | MASTER_DATA_VIEW   | priorities | none | N | |
| GET    | /api/v3/master/priorities/{code}                           | app/api/v3/master_data/routes.py:1349 | JWT | MASTER_DATA_VIEW   | priorities | none | N | |
| POST   | /api/v3/master/priorities/create                           | app/api/v3/master_data/routes.py:1365 | JWT | MASTER_DATA_MANAGE | priorities | none | N | |
| PATCH  | /api/v3/master/priorities/{code}                           | app/api/v3/master_data/routes.py:1398 | JWT | MASTER_DATA_MANAGE | priorities | none | N | |
| DELETE | /api/v3/master/priorities/{code}                           | app/api/v3/master_data/routes.py:1430 | JWT | MASTER_DATA_MANAGE | priorities | none | N | |
| POST   | /api/v3/master/priorities/{code}/restore                   | app/api/v3/master_data/routes.py:1452 | JWT | MASTER_DATA_MANAGE | priorities | none | N | |
| GET    | /api/v3/dashboard/summary                                  | app/api/v3/dashboard/routes.py:38   | JWT | require_admin | projects, milestones, activities, vendors, divisions | none | N | admin only |
| GET    | /api/v3/dashboard/projects                                 | app/api/v3/dashboard/routes.py:58   | JWT | require_admin | projects | none | N | |
| GET    | /api/v3/dashboard/projects/{project_uuid}                  | app/api/v3/dashboard/routes.py:90   | JWT | require_admin | projects, milestones, activities | none | N | |
| GET    | /api/v3/dashboard/projects/{project_uuid}/items            | app/api/v3/dashboard/routes.py:111  | JWT | require_admin | milestones, activities | none | N | |
| GET    | /api/v3/dashboard/organisations                            | app/api/v3/dashboard/routes.py:140  | JWT | require_admin | vendors, projects, project_vendors | none | N | |
| GET    | /api/v3/dashboard/organisations/{vendor_id}                | app/api/v3/dashboard/routes.py:156  | JWT | require_admin | vendors, projects | none | N | |
| GET    | /                                                          | app/main.py:240 | none (public) | none | -- | none | N | root |
| GET    | /health                                                    | app/main.py:209 | none (public) | none | -- (touches storage) | none | N | |
| GET    | /files/{storage_key:path}                                  | app/main.py:132 | none (public, conditional) | none | -- (filesystem read) | none | N | only when FILE_SERVER_LOCAL_FALLBACK_ENABLED |

INFERRED route counts:
- CURRENT routes: ~105 (project-domain, comments, attachments, master_data, dashboard, tree, root/health/files, priorities)
- LEGACY routes (deprecated wire surface superseded by `/api/v3/master/*`): 11 (catalogs:2, resource_types:2, vendors:7)

Note: comments and attachments each register one path string four times via `_make_*_endpoint` factories (app/api/v3/comments/routes.py:71-91, app/api/v3/attachments/routes.py:69-94) -- 4 + 4 = 8 each, plus their DELETE.

INFERRED: NO routes for `work_packages`, `meetings`, `work_package_types`, `project_members`, `users`, `roles`, `permissions` in `app/api/v3/`. Stated explicitly in app/api/router.py:3-7 -- those modules are deliberately not registered. See LEGACY inventory (Section 9) for residual files.

## 4. Models

OBSERVED: All models live in `app/infrastructure/db/models/` (no schema name set; default `public`). Model package `__init__.py` notes (file:1-15) which models are kept as "read-only references" for cross-service queries.

| TABLE | MODEL CLASS (file:line) | KEY COLUMNS | FKs | SOFT-DELETE? | LEGACY? | NOTES |
|---|---|---|---|---|---|---|
| projects | ProjectModel (app/infrastructure/db/models/project.py:23) | id (PK, UUID), project_code, name, status, parent_id, deleted_at | parent_id->projects.id; created_by/updated_by/deleted_by->users.id | Y | N | shared with monolith |
| project_audit_logs | ProjectAuditLogModel (app/infrastructure/db/models/project_audit_log.py:33) | id (PK), project_id, action, actor_id, actor_code, actor_role | project_id->projects.id; actor_id->users.id | N | N | doc 47, this svc owns |
| project_vendors | ProjectVendorModel (app/infrastructure/db/models/project_vendor.py:18) | project_id+vendor_id (composite-ish), deleted_at | project_id->projects.id, vendor_id->vendors.id | Y | N | M:N |
| project_status_transitions | ProjectStatusTransitionModel (app/infrastructure/db/models/project_status_transition.py:44) | id (PK), from_status, to_status, active, requires_admin | -- | N (active flag) | N | catalog |
| project_categories | ProjectCategoryModel (app/infrastructure/db/models/project_category.py:27) | id, code, label, is_builtin, active | -- | N | N | doc 37 |
| milestones | MilestoneModel (app/infrastructure/db/models/milestone.py:24) | id (PK), project_id, name, status, actual_start_date, actual_end_date, deleted_at | project_id->projects.id | Y | N | |
| milestone_dependencies | MilestoneDependencyModel (app/infrastructure/db/models/milestone_dependency.py:25) | source_milestone_id, target_milestone_id, project_id, deleted_at | both->milestones.id, project_id->projects.id | Y | N | |
| milestone_statuses | MilestoneStatusModel (app/infrastructure/db/models/milestone_status.py:28) | id, code, label, is_builtin, is_terminal, active | -- | N | N | doc 37 |
| milestone_vendors | MilestoneVendorModel (app/infrastructure/db/models/milestone_vendor.py:15) | milestone_id+vendor_id | both | Y | N | |
| activities | ActivityModel (app/infrastructure/db/models/activity.py:16) | id (PK), project_id, milestone_id, name, status, position, vendor_id, deleted_at | project_id, milestone_id, vendor_id | Y | N | priority FK to priorities.code (doc 41) |
| activity_dependencies | ActivityDependencyModel (app/infrastructure/db/models/activity_dependency.py:40) | source_activity_id, target_activity_id, project_id, deleted_at | both->activities.id, project->projects.id | Y | N | |
| activity_resources | ActivityResourceModel (app/infrastructure/db/models/activity_resource.py:16) | activity_id, ... | activity_id->activities.id | N | N | |
| activity_types | ActivityTypeModel (app/infrastructure/db/models/activity_type.py:27) | id, code, label, is_builtin, active | -- | N | N | doc 37 |
| activity_statuses | ActivityStatusModel (app/infrastructure/db/models/activity_status.py:27) | id, code, label, is_builtin, is_terminal, active | -- | N | N | doc 37 |
| tasks | TaskModel (app/infrastructure/db/models/task.py:18) | id (PK), project_id, activity_id, name, status, deleted_at | project_id, activity_id | Y | N | |
| task_dependencies | TaskDependencyModel (app/infrastructure/db/models/task_dependency.py:26) | source_task_id, target_task_id, project_id, deleted_at | -- | Y | N | |
| task_resources | TaskResourceModel (app/infrastructure/db/models/task_resource.py:17) | task_id, ... | task_id->tasks.id | N | N | |
| subtasks | SubtaskModel (app/infrastructure/db/models/subtask.py:36) | id (PK), project_id, task_id, parent_subtask_id, name, status, deleted_at | project_id, task_id, parent_subtask_id->subtasks.id | Y | N | nested |
| subtask_dependencies | SubtaskDependencyModel (app/infrastructure/db/models/subtask_dependency.py:21) | source/target, project_id, deleted_at | -- | Y | N | |
| subtask_resources | SubtaskResourceModel (app/infrastructure/db/models/subtask_resource.py:17) | subtask_id, ... | subtask_id | N | N | |
| comments | CommentModel (app/infrastructure/db/models/comment.py:40) | id (PK), target_kind, target_id, body, attachments (JSON), author_user_id, deleted_at | author_user_id, deleted_by -> users.id | Y | N | polymorphic; attachments table retired (doc 35) |
| divisions | DivisionModel (app/infrastructure/db/models/division.py:42) | id, code, label, is_builtin, active, email, phone_number | -- | N (active) | N | catalog |
| priorities | PriorityModel (app/infrastructure/db/models/priority.py:21) | id, code (UPPER), name, position, is_builtin, active, deleted_at | -- | Y | N | doc 41 |
| resource_types | ResourceTypeModel (app/infrastructure/db/models/resource_type.py:20) | id, code, name, active | -- | N | N | catalog |
| vendors | VendorModel (app/infrastructure/db/models/vendor.py:32) | id (PK), name, vendor_code, email, deleted_at | -- | Y | N | shared with monolith |
| users | UserModel (app/infrastructure/db/models/user.py:23) | id (PK UUID), user_code, login, email, hashed_password, status, vendor_id, division, deleted_at | vendor_id->vendors.id | Y (also app DELETE) | N (read-only) | **owned by user-service**; project-svc never writes; FK target |
| revoked_tokens | RevokedTokenModel (app/infrastructure/db/models/revoked_token.py:26) | jti (PK), user_id, revoked_at, expires_at | user_id->users.id | N | N (read-only) | **owned by user-service**; project-svc reads for auth check |
| roles | RoleModel (app/infrastructure/db/models/role.py:24) | id, name, description | -- | N | N (read-only) | **user-service owned**; doc-21B RBAC |
| permissions | PermissionModel (app/infrastructure/db/models/permission.py:26) | id, code (e.g. projects:read), description | -- | N | N (read-only) | **user-service owned** |
| role_permissions | RolePermissionModel (app/infrastructure/db/models/role_permission.py:15) | role_id+permission_id | role_id->roles.id, permission_id->permissions.id | N | N (read-only) | **user-service owned** |
| user_roles | UserRoleModel (app/infrastructure/db/models/user_role.py:15) | user_id+role_id | both | N | N (read-only) | **user-service owned**; legacy global tier |
| user_permissions | UserPermissionModel (app/infrastructure/db/models/user_permission.py:19) | user_id+permission_id, allow/deny | both | N | N (read-only) | **user-service owned** |
| user_role_assignments | UserRoleAssignmentModel (app/infrastructure/db/models/user_role_assignment.py:37) | id, user_id, role_id, organization_id (vendor), project_id | user_id, role_id, organization_id->vendors.id, project_id->projects.id | N | N (read-only for reads; project-svc only joins) | **user-service owned**; doc-21B scoped tier |

OBSERVED: model count = 32 ORM classes. CURRENT (owned-or-shared by project-svc) = 25. READ-ONLY mirrors (user-service-owned tables referenced for FK / auth checks) = 7 (users, revoked_tokens, roles, permissions, role_permissions, user_roles, user_permissions, user_role_assignments — 8 actually).

INFERRED: There are NO models for `work_packages`, `work_package_types`, `meetings`, `meeting_participants`, `agenda_items`, `project_members`, `notification_log`, `otp_code`, `password_reset_token`, `notification_template`, `attachments` (the old separate table). Confirmed via app/infrastructure/db/models/__init__.py:1-15 commentary and Grep over models/.

OBSERVED soft-delete pattern: `deleted_at` (timestamp) + `deleted_by` (user-id FK) — uniform across `projects`, `milestones`, `activities`, `tasks`, `subtasks`, `comments`, `vendors`, `priorities`, and all `*_dependencies` and `*_vendors` join tables (16 tables total per Grep).

## 5. Alembic migrations

Version table: `alembic_version_project_svc` (alembic/env.py:39). Deliberately separate from monolith's `alembic_version` and user-service's `alembic_version_user_svc` (alembic/env.py:36-38). `target_metadata` = `Base.metadata` from this service only (alembic/env.py:34) -- this service migrates **only its own tables**.

Linear chain (no branches, single head):

| FILENAME | REVISION | DOWN_REVISION | SUMMARY | TYPE | LEGACY-ADJACENT? |
|---|---|---|---|---|---|
| 8a3c5e7f9b21_initial_project_service_schema.py | 8a3c5e7f9b21 | None | Initial schema for project-svc owned tables (CREATE TABLE IF NOT EXISTS) | schema | N |
| c2d4e7f9a1b4_doc20_to_36_parity.py | c2d4e7f9a1b4 | 8a3c5e7f9b21 | Doc 20-36 parity (consolidates with monolith state) | schema | N |
| d3e5f7a9b1c2_doc37_static_data_masters.py | d3e5f7a9b1c2 | c2d4e7f9a1b4 | Doc 37 part 1 -- project_categories, activity_types, milestone_statuses, activity_statuses | schema + data | N |
| b7c2e8f4a9d6_doc38_field_trim.py | b7c2e8f4a9d6 | d3e5f7a9b1c2 | Doc 38 -- trim activity create fields | schema | N |
| d2c4f8a9e1b3_doc39_activity_concerned_divisions.py | d2c4f8a9e1b3 | b7c2e8f4a9d6 | Doc 39 -- activities.concerned_division list | schema | N |
| e3f5b7a8c1d4_add_priorities_catalog.py | e3f5b7a8c1d4 | d2c4f8a9e1b3 | Doc 41 -- priorities catalog | schema + data | N |
| c8a3d4f6e9b2_assigned_to_on_ts.py | c8a3d4f6e9b2 | e3f5b7a8c1d4 | assigned_to on tasks/subtasks | schema | N |
| b5e7f2a8c9d3_priority_on_mts.py | b5e7f2a8c9d3 | c8a3d4f6e9b2 | priority FK on milestones/tasks/subtasks | schema | N |
| d6b9c4f8a3e1_milestone_actual_dates.py | d6b9c4f8a3e1 | b5e7f2a8c9d3 | milestones.actual_start_date / actual_end_date | schema | N |
| d2c4f1a9b8e7_uppercase_priority_codes.py | d2c4f1a9b8e7 | d6b9c4f8a3e1 | Normalize priority codes to UPPER | data | N |
| b1d3e7a9c204_doc47_audit_log_enrichment.py | b1d3e7a9c204 | d2c4f1a9b8e7 | Doc 47 -- project_audit_logs enrichment | schema | N |
| c3a8d1f7e542_doc47_audit_log_actor_code.py | c3a8d1f7e542 | b1d3e7a9c204 | Doc 47 -- audit log actor_code column | schema | N |
| d4f9b2e8a317_backfill_actor_role.py | d4f9b2e8a317 | c3a8d1f7e542 | Backfill audit_logs.actor_role | data | N |

OBSERVED: HEAD = `d4f9b2e8a317` (linear -- single head, no orphans, no merges).
OBSERVED: Migrations are NOT modifying any user-service-owned table -- all operations target project-svc's own tables. The initial migration (8a3c5e7f9b21) uses CREATE TABLE IF NOT EXISTS semantics (per app/infrastructure/db/session.py:44-47) so running against the shared monolith DB is a no-op for already-existing tables.

[UNVERIFIED]: I did not open each migration body. Whether any of them quietly add columns to e.g. `users` or `roles` would require reading every file. Filenames + initial-schema docstring suggest no.

INFERRED: A duplicate copy of every migration exists under `src/alembic/versions/` (legacy alternate tree -- see Section 9). The production Dockerfile only copies the top-level `alembic/` (Dockerfile:31), so `src/alembic/` is dead weight.

## 6. Auth & RBAC

- OBSERVED JWT decode location: `decode_access_token` in app/core/security.py:89 -- library is `python-jose[cryptography]` (`from jose import ... jwt`, app/core/security.py:9). Uses `settings.SECRET_KEY` (env var `SECRET_KEY`) and `settings.ALGORITHM` (HS256). Called by `AuthenticationMiddleware.dispatch` (app/core/middleware/auth.py:67).
- OBSERVED auth middleware: `AuthenticationMiddleware` (app/core/middleware/auth.py:50-105). Wired in app/main.py:57. Hydrates per-request state from the JWT: `user_id`, `user_login`, `user_permissions: Set[str]`, `is_admin: bool`, `token_jti`, `token_exp`.
- OBSERVED revoked-token check: `RevokedTokenRepository.is_revoked(jti)` (app/infrastructure/db/repositories/revoked_token_repository.py:19-36). Queries `revoked_tokens` table (PK `jti`) with `expires_at > now()` filter; revoked & unexpired -> request continues as ANONYMOUS (perms empty). Wired via `AuthenticationMiddleware._is_revoked` (app/core/middleware/auth.py:108-117). What it checks: the JWT's `jti` claim against the `revoked_tokens.jti` PK.
- OBSERVED Permission check pattern: `require_permission(perm_code)` (app/core/middleware/rbac.py:29) -- FastAPI `Depends(...)` factory that reads `request.state.user_permissions: Set[str]` and rejects with `AuthenticationError` if anonymous, `AuthorizationError` if permission code absent. Permission codes are strings like `"projects:read"` (app/core/permissions.py / app/core/rbac.py `Permission` enum -- both forms accepted, `.value` is read off enum members at app/core/middleware/rbac.py:37). Used at route level via `dependencies=[require_permission(PROJECTS_CREATE)]` (e.g. app/api/v3/projects/routes.py:51).
- OBSERVED admin check: `require_admin()` (app/core/middleware/rbac.py:60) -- checks `request.state.is_admin` set by `RbacRepository.user_has_admin_role(user_id)`. Used at router level on the dashboard router (app/api/v3/dashboard/routes.py:22) and inside vendor PATCH gate (vendors/routes.py:308,327,478).
- OBSERVED auth-only fallback: `require_authenticated()` (app/core/middleware/rbac.py:50) -- used on catalog reads and the comment/attachment DELETE endpoints.
- OBSERVED permissions hydrator: `AuthenticationMiddleware._load_user_permissions` (app/core/middleware/auth.py:120-133) calls `RbacRepository.effective_permissions_for_user(user_id)` (app/infrastructure/db/repositories/rbac_repository.py) -- pulls `role_permissions JOIN user_role_assignments` etc from the user-service-owned tables (read-only here).
- OBSERVED token issuance: `create_access_token` / `create_refresh_token` exist in app/core/security.py:46,139 but are NOT called from any route in this service -- the route handlers only verify. Tokens are minted by user-service (per app/core/config.py:32-39 commentary).

[UNVERIFIED] One-line drift assessment: Same shape as monolith (string-coded permissions, JWT verify with shared SECRET_KEY, revoked_tokens blacklist). The pre-doc-26-token guard at app/core/middleware/auth.py:75-85 indicates active version coordination with user-service. No structural drift observed -- but I did NOT diff the monolith middleware byte-for-byte, so call this CURRENT but verify against `C:\Programming\PMIS\PMIS-OpenProject\` before porting.

## 7. Cross-service HTTP calls

| FROM (file:line) | TO | METHOD | PURPOSE |
|---|---|---|---|
| (none found) | -- | -- | -- |

OBSERVED: No outbound `httpx`/`requests`/`urllib.request` HTTP calls to any sibling PMIS service. `httpx` (requirements.txt:13) is used only by the FastAPI `TestClient` in tests (tests/conftest.py and tests/test_*.py via `from fastapi.testclient import TestClient`).
- OBSERVED: `HttpExternalFileClient` exists at app/infrastructure/storage/external_file_client.py:147 but is **a stub** -- its `upload()` (line 170-184) routes through the local fallback and explicitly logs "HttpExternalFileClient is a stub". The class doesn't import `httpx` or `requests`.
- OBSERVED: All cross-service coordination is via the **shared Postgres database** (e.g. project-svc reads `users`, `user_role_assignments`, `roles`, `revoked_tokens` directly).
- OBSERVED: Health check docker-compose uses `urllib.request.urlopen` against localhost only (docker-compose.yml:23-24) -- internal liveness probe, not cross-service.

INFERRED: There is no event bus, no message queue, no webhook out. project-svc does not call user-svc for user lookups (it joins on the shared `users` table) and does not call notification-svc on assignment (no integration point exists -- notification surface lives entirely on user-service per app/core/config.py:146-147).

## 8. Folder shape

OBSERVED: file count under `app/` = 221 .py files. LOC under `app/` (Grep `.*` counts all lines, equivalent to wc -l on every file) = ~32,521 lines.

OBSERVED tree of `app/` to depth 3 (one-line per node):

```
app/
  __init__.py
  main.py                        # FastAPI entry, 247 lines
  api/
    __init__.py
    router.py                    # central v3 router; 69 lines
    v3/
      _inline_attachments.py     # multipart dispatch helper, 456 lines
      activities/                # routes + controller + services/ + schemas + permissions
      attachments/               # routes + controller + services/
      catalogs/                  # routes (legacy divisions, project_status_transitions, priorities)
      comments/                  # routes + controller + services/ + schemas + permissions + _target_helper
      dashboard/                 # routes + controller + services/ + schemas
      master_data/               # routes (huge -- 1462 LOC) + schemas
      milestones/                # routes + controller + services/ + schemas + permissions
      projects/                  # routes (1046 LOC) + controller (489 LOC) + services/ + schemas + permissions
      resource_types/            # routes (legacy)
      subtasks/                  # routes + controller + services/ + schemas + permissions
      tasks/                     # routes + controller + services/ + schemas + permissions
      tree/                      # routes + service (481 LOC)
      vendors/                   # routes (738 LOC) + schemas + user_assignments
  core/
    base_controller.py           # 89
    config.py                    # 150
    dependencies.py              # 27
    errors.py                    # 79
    permissions.py               # 305 (string codes)
    project_lock.py              # 91
    rbac.py                      # 129 (enum-form Permission)
    response.py                  # 583
    security.py                  # 178 (JWT + argon2)
    middleware/
      auth.py logging.py rbac.py
  domain/                        # DDD entities (dataclasses-style)
    activities/  comments/  milestones/  priorities/  projects/  resource_types/  subtasks/  tasks/  vendors/
  infrastructure/
    db/
      models/                    # 33 ORM model files
      repositories/              # 14 repo files (project, activity, milestone, task, subtask, comment, dependency, dashboard, vendor, division, priority, resource_type, project_audit_log, project_status_transition, rbac, revoked_token)
      session.py utc_datetime.py
    storage/
      file_storage.py            # 267
      external_file_client.py    # 231 (HttpExternalFileClient is a stub)
  shared/                        # 19 small helpers (labels.py 757, dep_block.py 397, dep_date_rules.py 308, code_generators.py 236, ...)
```

OBSERVED -- THREE resource folders sampled under `app/api/v3/`:

(a) `projects/` -- files present: `__init__.py`, `controller.py` (489), `permissions.py` (17), `routes.py` (1046), `schemas.py` (252), `services/` ({audit, close, create, delete, get, list, publish, save, transitions, update, upsert}.py). Total 12 service files. **Most fragmented module.**

(b) `tasks/` -- files present: `__init__.py`, `controller.py` (362), `permissions.py` (8), `routes.py` (151), `schemas.py` (121), `services/` ({create, delete, get, list, restore, update}.py). Total 6 service files. **Consistent**.

(c) `dashboard/` -- files present: `__init__.py`, `controller.py` (101), `routes.py` (161), `schemas.py` (237), `services/` ({common, organisations, project_detail, project_items, projects_list, summary}.py). Total 6 service files. **Consistent and clean -- pure read service.** No `permissions.py` because the router uses `require_admin()` (dashboard/routes.py:22) instead of per-permission codes.

OBSERVED divergence from notification-svc target shape (which the user described as FLAT):
- This service uses both **deep-nested** `app/api/v3/<resource>/services/{get,list,delete,restore,create,...}.py` (one file per verb -- inherited from monolith) AND **DDD-ish** structure: `app/{core, domain, infrastructure, shared}` at the same time. Hybrid -- not flat.
- `domain/` contains lean dataclasses-style entity files (e.g. `domain/projects/project.py` 97 lines) parallel to `infrastructure/db/models/` ORM models. The pattern: each entity has both a domain class and an ORM model that maps to the same table.
- `infrastructure/db/repositories/` is where the SQL lives -- 14 repository files, used by both services/ and route handlers directly.

Where business logic lives: the deep `app/api/v3/<resource>/services/*.py` files (verb-per-file pattern) -- e.g. `projects/services/create.py` is 262 lines of project-creation logic. The DDD `domain/` and `infrastructure/` layers are present but **the route handlers and `services/` files do most of the orchestration** (the typical pattern is: route -> controller -> services/<verb>.py -> repositories). This means a flat refactor needs to collapse the per-verb files into one `<resource>.py` module each.

OBSERVED: All `infrastructure/db/repositories/*.py` re-export through `__init__.py` (file:1-38). Repository LOC heavy hitters: dependency_repository.py (872), milestone_repository.py (439), rbac_repository.py (430), activity_repository.py (418), project_repository.py (365), dashboard_repository.py (342).

## 9. LEGACY inventory (PRIORITY)

### 9.0 The `src/` duplicate tree -- the "old implementation of project modules"

OBSERVED: A complete second copy of the service lives at `C:\Programming\PMIS\PMIS-project-management\src\` (mirrors `app/`, `alembic/`, `tests/`, `requirements.txt`, `Dockerfile`, `.env.example`, `docker-compose.yml`, README.md -- a self-contained alternate). This is **THE "old implementation of project modules"** the user flagged.

Evidence it is the LEGACY copy:
- The production `Dockerfile:30-32` copies ONLY top-level `app/`, `alembic/`, `alembic.ini` -- `src/` is NOT in the image.
- The top-level `app/api/router.py` is the **active** router (imported via `app/main.py:12`) and **adds `dashboard_router`** (router.py:36, 69) plus the explanatory header (router.py:1-7 "In-use modules only"). The `src/app/api/router.py:1-7` has the SAME header but **lacks** `dashboard_router` registration -- so `src/` is an earlier snapshot.
- `.pyc` cache files exist in the top-level `app/` tree (e.g. `app/api/v3/projects/services/__pycache__/*.cpython-312.pyc` from the Glob output in §3 prep). No `__pycache__` in `src/`. The top-level tree has actually been executed.
- `src/` contains `infrastructure/db/models/project_member.py` (a model for the dormant `project_members` table); the top-level `app/infrastructure/db/models/` does NOT (Glob confirmed). Top-level `__init__.py:41-42` says "project_members retired -- unified into user_role_assignments".
- `src/tests/` has only 9 tests; top-level `tests/` has 19. Top-level is newer.

Two `projects/` situations (the user asked):
- ACTIVE: `app/api/v3/projects/` (top-level) -- routes.py 1046 LOC, controller.py 489 LOC, 11 service files including delete.py + audit.py.
- LEGACY: `src/app/api/v3/projects/` -- mirror of the active one, slightly older. Compare file:line:
  - app/api/v3/projects/routes.py:46 (`router = APIRouter(prefix="/projects", tags=["projects"])`) **vs**
  - src/app/api/v3/projects/routes.py (same module path, parallel).

Files in `src/` -- all SUSPECTED-LEGACY (dead copy):
- src/app/ -- entire tree (~95 .py files in src/app/api/v3/ + src/app/core/ + src/app/domain/ + src/app/infrastructure/ + src/app/main.py + src/app/shared/)
- src/alembic/versions/ -- 6 migration files (duplicates of top-level)
- src/tests/ -- 9 test files (subset of top-level tests/)
- src/Dockerfile, src/docker-compose.yml, src/requirements.txt, src/alembic.ini, src/pytest.ini, src/README.md, src/.env.example, src/.dockerignore, src/.gitignore

### 9.1 `work_packages` -- LEGACY (dormant, removed from active code)

- Routes (active): **none**. app/api/v3/ has no `work_packages` folder.
- Routes (legacy `src/`): **none**. src/app/api/v3/ also has no `work_packages` folder.
- Models: **none** in either tree.
- Schemas: **none**.
- Services: **none**.
- Migrations: **none** that create `work_packages` tables in alembic/versions/ (the initial schema 8a3c5e7f9b21 owns project-svc tables only).
- Tests: **none**.
- Permission codes (LEGACY definitions, unused by routes here): `src/app/core/permissions.py:86-89` (`WORK_PACKAGES_VIEW/CREATE/UPDATE/DELETE`), `src/app/core/rbac.py:78-81`. The top-level `app/core/permissions.py` and `app/core/rbac.py` should be re-grepped (only checked `src/`) -- but app/api/router.py:1-7 explicitly excludes them and no `work_packages_*` constants are imported by any active route.
- Verdict: `work_packages` is **already dead code** in this service. Nothing to delete except the residual permission-code strings in `app/core/permissions.py` and `app/core/rbac.py` -- needs verification.

### 9.2 `meetings` -- LEGACY (dormant, removed from active code)

- Routes (active): **none**. app/api/v3/ has no `meetings` folder.
- Routes (legacy `src/`): **none**.
- Models: **none** in either tree.
- Schemas: **none**.
- Services: **none**.
- Migrations: **none**.
- Tests: **none**.
- Residual references:
  - src/app/core/permissions.py:94-97 -- MEETINGS_VIEW/CREATE/UPDATE/DELETE constants.
  - src/app/core/rbac.py:87-90 -- enum members.
  - src/app/core/response.py:287, 368, 385 -- HAL `_links` builder writes `/meetings/{id}` and `/work_packages/{id}` URLs into responses. **Live in src/ ONLY** -- needs verification whether the active top-level `app/core/response.py` (583 LOC) still has those link templates. Confirmed `app/core/response.py` matches in the work_packages/meetings Grep above -- needs spot check.
- Verdict: `meetings` is dead code. Same disposition as work_packages.

### 9.3 "Old project impl" -- the `src/` tree (covered in §9.0)

The user's third LEGACY category. See §9.0 above. The two `projects/` implementations are:
1. CURRENT: `C:\Programming\PMIS\PMIS-project-management\app\api\v3\projects\` (top-level, imported by app/api/router.py:22).
2. LEGACY: `C:\Programming\PMIS\PMIS-project-management\src\app\api\v3\projects\` (mirror, never reached by app.main:app at runtime).

### 9.4 `project_members` -- LEGACY model only

- Routes: **none** in either tree.
- Models (LEGACY): src/app/infrastructure/db/models/project_member.py:14 (`ProjectMemberModel`, `__tablename__ = "project_members"`). Joins to `users.id` and `projects.id`.
- Models (CURRENT): top-level `app/infrastructure/db/models/__init__.py:41-42` explicitly says "project_members retired -- unified into user_role_assignments (project scope). See monolith alembic migration baddc1146b85." So the table itself was migrated upstream by the monolith; project-svc just doesn't re-create or write it.
- Schemas / Services / Tests: **none**.
- Verdict: model file exists only in `src/`. The `project_members` table itself, if still in the shared DB, is owned by the monolith. Refactor target should NOT carry this model.

### 9.5 `users` / `roles` / `permissions` -- user-service owned (read-only mirrors)

Not legacy per se -- but flagged because they're "owned elsewhere":
- Models present in active `app/infrastructure/db/models/`: `user.py`, `revoked_token.py`, `role.py`, `permission.py`, `role_permission.py`, `user_role.py`, `user_role_assignment.py`, `user_permission.py` -- all marked read-only in app/infrastructure/db/models/__init__.py:1-15. project-svc only **reads** these tables (auth middleware + scope checks); writes happen on user-service.
- Routes for these: **none** in this service. Stated in app/api/router.py:1-7.
- Disposition for the refactor: keep the model files as FK targets, but document them as "read-only references owned by user-service."

### 9.6 No `*_old*` / `*_legacy*` / `*_v1*` / `*alt*` / `*backup*` / `*deprecated*` named files

OBSERVED: All six Glob patterns returned 0 files. The LEGACY surface in this repo is concentrated entirely in the `src/` duplicate tree, not in suffix-tagged filenames.

### 9.7 Tests covering LEGACY

OBSERVED tests (top-level `tests/`):
- tests/test_doc53_assignee_scope.py:?? -- references `project_members` table per Grep (verify before deleting).
- tests/test_scoped_rbac_mirror.py -- references `project_members` (legacy table, may be testing migration-away path).
- src/tests/ -- entire folder is LEGACY (alternate test tree paired with src/app/).

No tests for work_packages or meetings exist anywhere.

### 9.8 Quick deletion plan (for the refactor)

Safe to delete in flat-shape rebuild:
1. The whole `src/` subtree (`src/app/`, `src/alembic/`, `src/tests/`, plus the docker/env files inside `src/`) -- ~95 Python files in src/app/, never executed.
2. The legacy wire surface routes (deprecated by master_data):
   - `app/api/v3/catalogs/routes.py` (193 LOC) -- 3 GETs (divisions, project_status_transitions, priorities) -- but priorities is CURRENT, keep that one.
   - `app/api/v3/resource_types/routes.py` (87 LOC) -- 2 endpoints, both deprecated.
   - `app/api/v3/vendors/routes.py` (738 LOC) -- 7 endpoints all marked deprecated, but they're DELEGATED FROM master_data routes (app/api/v3/master_data/routes.py:46-54) -- can't just delete; need to inline into master_data.
3. The `project_member.py` model (`src/`-only -- already not in active tree).
4. Audit residual permission-code constants for `WORK_PACKAGES_*`, `MEETINGS_*`, `PROJECT_MEMBERS_*` in top-level `app/core/permissions.py` and `app/core/rbac.py` -- needs verification.

Still verify before delete:
- app/api/v3/projects/routes.py imports `PROJECT_MEMBERS_READ` from `app/core/permissions.py` (projects/routes.py:15) -- so that one constant is **still in use** by the assignable-users endpoint. Do NOT delete PROJECT_MEMBERS_READ.
- app/core/response.py:287,368,385 -- the link templates that produce `/meetings/{id}` and `/work_packages/{id}` URLs. Verify they're not still emitted by some active response builder before deleting.

### 9.9 Spot-check: legacy refs DO exist in active `app/core/`

After the Section 9 write I re-grepped the **active** top-level `app/core/` for `meetings` / `work_packages` -- they're NOT confined to `src/`. Findings:

- app/core/rbac.py:78-90 -- WORK_PACKAGES_* + MEETINGS_* enum members are present in the active Permission enum.
- app/core/permissions.py:86-97 -- same string constants present.
- app/core/permissions.py:177-187 -- `PermissionDef(...)` rows still seed these into the permission catalog at startup.
- app/core/permissions.py:255, 257, 269, 298 -- still referenced from role-bundle constants.
- app/core/response.py:336, 417, 434 -- link templates `/meetings/{meeting_id}` and `/work_packages/{work_package_id}` are present in the active response builder (HAL link helper for agenda-item style responses).

INFERRED: These are **dead permission constants + dead link-builder branches** kept around in the active codebase. They are not exercised by any current route (router.py:1-7 doesn't register meetings/work_packages routers; no model exists; no service consumes the response helper paths for these). Safe to delete during refactor, but they're not in `src/` -- they're in the active code.

## 10. Notable findings / risks

### Shape divergence from target (flat, modeled on notification-service)
- This service is a **hybrid**: deep-nested per-verb `app/api/v3/<resource>/services/{get,list,delete,restore,create,update}.py` (inherited from monolith) **plus** DDD-ish `app/{core,domain,infrastructure,shared}`. The flat refactor will need to collapse 11 service files for `projects/` into one `projects.py`, 6 each for tasks/subtasks/milestones/activities/comments/attachments/dashboard, and so on. Largest collapse target: app/api/v3/projects/ (1046+489+11*~150 LOC).
- `master_data/routes.py` is **1,462 LOC** and registers ~50 endpoints in one file. A flat shape probably wants this split per-catalog (8 sub-files), OR kept as-is but renamed.
- `vendors/routes.py` is **738 LOC** but every route is `Deprecation`-stamped and **delegated to by master_data**. The delegation pattern (app/api/v3/master_data/routes.py:46-54 imports the handlers directly) means vendors/routes.py is the actual implementation while master_data is a thin wrapper. Refactor needs to invert: implementation lives in flat `vendors.py`, master_data either re-imports or is removed.

### Drift vs monolith for shared tables (projects)
- `projects` table is shared with monolith. project-svc's `ProjectModel` (app/infrastructure/db/models/project.py:23) defines columns including `parent_id` (self-FK), `actual_start_date`, `actual_end_date`, `category`, `category_other`, `category_other_reason`. [UNVERIFIED] column-level diff vs monolith requires reading the monolith's `ProjectModel` -- the user-supplied memory says monolith and microservice "divergence" exists at `C:\Programming\PMIS\PMIS-OpenProject\`.
- Migration coordination: alembic uses a **separate version table** `alembic_version_project_svc` (alembic/env.py:39) and CREATE TABLE IF NOT EXISTS semantics (session.py:44-47) -- so project-svc's migrations are no-ops against the shared DB if the monolith already created the row. But this also means project-svc DOESN'T add columns the monolith doesn't have. **Column drift can only have arrived via the monolith's migration chain**, not from project-svc.
- This is fine for the refactor, but call out: any column added to `ProjectModel` here without a paired monolith migration will silently miss on monolith-first DBs.

### Auth gate has runtime cost
- Every authenticated request hits the DB twice: once for `revoked_tokens.is_revoked(jti)` (auth.py:108-117) and once for `RbacRepository.effective_permissions_for_user(user_id)` (auth.py:120-133). Both open a **fresh SessionLocal** (not the request-bound one) -- two connections per request. Risk on busy endpoints.

### `src/` duplicate tree is a maintenance bomb
- ~95 Python files in `src/app/` that nothing imports. Easy to accidentally edit the wrong copy. Should be deleted in the refactor (with a final `diff -r app/ src/app/` to make sure no isolated bug-fix is stranded there).

### Decisions for human before porting
1. **The `vendors/` ↔ `master_data/` delegation knot** -- choose whether the flat service keeps the legacy `/api/v3/vendors/*` wire surface (with Deprecation header) or hard-cuts to `/api/v3/master/vendors/*` only. FE migration status determines this.
2. **Whether to keep `app/api/v3/catalogs/routes.py:171` (`GET /api/v3/priorities`)** -- it's separate from the `/api/v3/master/priorities` admin path because the FE picker needs an unprivileged read. Keep but move.
3. **Soft-delete `deleted_at`/`deleted_by` discipline** -- mixed with `active: bool` on catalogs. Pick one. Catalogs use `active`; project-domain tables use `deleted_at`. Refactor target should standardize.
4. **`UserModel` etc as "read-only references"** -- can the service work without compile-time imports of user-service tables, or do we keep them for ORM-level joins in audit-log / assignable-users / vendor user_assignments queries?
5. **`HttpExternalFileClient` stub** -- delete entirely, or wire up real outbound HTTP to the file server? Currently dead code (external_file_client.py:170-184).
6. **The active core has dead `WORK_PACKAGES_*` / `MEETINGS_*` permission constants** (app/core/permissions.py:86-97, app/core/rbac.py:78-90). They get seeded into the permissions catalog if startup writes that table -- check before deleting.

### Test fixtures / data needing migration
- 19 test files in top-level `tests/` (tests/test_*.py). Sampled risk items:
  - tests/test_doc53_assignee_scope.py -- references `project_members` (legacy table, may be testing migration-away path).
  - tests/test_scoped_rbac_mirror.py -- references `project_members` -- verify still relevant.
  - tests/conftest.py -- session/DB fixture; switching from monolith-shared to per-service Postgres may invalidate fixtures.
  - src/tests/ -- 9 files, **delete entirely** (alternate fixture set for the dead src/ tree).
- pytest.ini exists at repo root; src/pytest.ini exists in src/. Single config file in the refactor target.
- `argon2-cffi` (requirements.txt:11) is listed but only `verify_password` (security.py:29) uses it, called from... [UNVERIFIED] possibly nowhere in this service (user-service handles login). Drop dependency? Saves a C-extension build.

### Risks to call out explicitly
1. The `src/` legacy tree may contain a bug-fix or feature that never made it back into `app/` -- a final diff is mandatory before deletion.
2. `revoked_token_repository.py:38-60` (`revoke()`) is exposed but never called from any route here -- if user-service signs JWTs but project-svc revokes them, we may have a coordination gap. Likely user-service handles revocation too; verify.
3. The custom `DATABASE_URL_MIGRATIONS` (config.py:56) -- if elevated creds aren't actually wired in deployment, `init_db()` will run alembic with regular DATABASE_URL. Look for prod env-var setup.



