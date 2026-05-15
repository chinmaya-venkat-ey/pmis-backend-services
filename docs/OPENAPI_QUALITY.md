# OpenAPI / Swagger Quality Bar

Phase 3 checklist. **Every endpoint must pass this checklist before its service's `MIGRATION_LOG.md` is presented for approval.**

Why this exists: today's monolith Swagger is patchy. Post-refactor, `/docs` for each service is the canonical API reference (for FE devs, operators, and Postman test users). Quality must be deliberate.

---

## Per-endpoint checklist

For every `@router.<method>(...)` decorator:

- [ ] **`summary`** is set, ≤60 characters, sentence case, no trailing period.
  - Good: `summary="Create a new user"`
  - Bad: `summary=""` or `summary="Endpoint that creates a user record in the database."`
- [ ] **`description`** is set, one paragraph (≤400 chars), explains:
  - What the endpoint does
  - When to call it
  - What it returns (success path)
  - Key side effects (e.g. "sends an OTP email", "soft-deletes the user")
- [ ] **`tags`** groups by resource: `tags=["users"]`, `tags=["dashboard"]`. NOT `tags=["api"]` or `tags=["v3"]`.
- [ ] **Request body** uses a Pydantic schema, and each `Field(...)` has a `description=`.
- [ ] **Response model** declared via `response_model=...` (so Swagger renders the response shape).
- [ ] **Error responses** documented via `responses={...}` for any non-200 returns:
  ```python
  responses={
      400: {"description": "Validation error"},
      403: {"description": "Caller lacks USERS_CREATE permission"},
      409: {"description": "Login already in use"},
  }
  ```
- [ ] **File-upload endpoints** declare params as `UploadFile = File(...)` (NOT `str`) so Swagger shows the "Choose files" file picker. Per PLAN.md §2.3.
- [ ] **Deprecated endpoints** mark `deprecated=True` AND `description` names the successor URL.
- [ ] **Authentication requirement** visible in Swagger:
  - `Depends(require_permission(...))` propagates automatically as a security requirement in OpenAPI.
  - `Depends(require_authenticated())` shows the lock icon.
  - Anonymous endpoints (login, OTP) have no auth dependency.

---

## CI gate

`tools/check_openapi_quality.py` (skeleton in tools/) will be implemented in Phase 3. It:

1. Imports each service's FastAPI app and dumps the OpenAPI spec.
2. Walks every operation.
3. Asserts:
   - `summary` present and non-empty
   - `description` present and ≥40 chars
   - `tags` is a non-empty list of one element matching `^[a-z_-]+$`
   - If request body is `multipart/form-data`, at least one parameter has `format=binary`
4. Fails CI on any failing operation, with a list of which endpoints are bad.

---

## Examples — good vs bad

### Good

```python
@router.post(
    "/users/create",
    response_model=UserResponse,
    status_code=201,
    summary="Create a new user",
    description=(
        "Creates a user record and (when 2FA is enabled at the org level) "
        "issues an enrolment email. Caller must hold users:create. "
        "Returns the created user with HAL links."
    ),
    tags=["users"],
    dependencies=[Depends(require_permission(USERS_CREATE))],
    responses={
        409: {"description": "Login or email already in use"},
        403: {"description": "Caller lacks users:create"},
    },
)
async def create_user(
    payload: UserCreateRequest,
    controller: UserController = Depends(get_user_controller),
) -> UserResponse:
    return await controller.create(payload)
```

### Bad (what NOT to do)

```python
@router.post("/users/create")             # no summary/description/tags/response_model
async def create_user(payload):           # untyped payload
    return user_service.create(payload)
```

---

## File-upload example

```python
@router.post(
    "/projects/{project_uuid}/attachments/upload",
    summary="Upload attachments to a project",
    description=(
        "Attach one or more files. Max 25 MB per file. "
        "Allowed: pdf, docx, xlsx, txt, csv, jpg, jpeg, png, heic, mp4, webm, mov. "
        "Returns a HAL Collection of created attachments."
    ),
    tags=["attachments"],
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

Swagger renders this with a multi-file picker.
