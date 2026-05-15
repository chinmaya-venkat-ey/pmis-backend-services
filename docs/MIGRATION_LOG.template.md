# <SERVICE_NAME> — Migration Log

> Filled in during Phase 3 when this service is ported. Replace `<SERVICE_NAME>` with e.g. `pmis-notification-management`.

## Source repos

- Monolith: `C:\Programming\PMIS\PMIS-OpenProject\app\...`
- Sibling extraction (if any): `C:\Programming\PMIS\PMIS-<svc>\...`

## Endpoint port table

For every `@router.<method>(...)` in this service, one row. Cite source `path:line` for each.

| METHOD | NEW PATH | HANDLER (new file:line) | SOURCE HANDLER (monolith or sibling path:line) | NOTES |
|---|---|---|---|---|
| | | | | |

## Models ported

| Table | New model (file:line) | Source (path:line) | Schema changes vs source |
|---|---|---|---|
| | | | |

## Alembic migrations added

| Revision | Description | Type (DDL / data / mixed) |
|---|---|---|
| | | |

## Cross-schema mirrors

| Mirrored table | New mirror declaration (file:line) | Source canonical (file:line) |
|---|---|---|
| | | |

## Cross-service HTTP calls (outbound)

| FROM (file:line) | TO (service + endpoint) | METHOD | Purpose |
|---|---|---|---|
| | | | |

## Tests

| Layer | Count | Coverage |
|---|---|---|
| Unit | | |
| Integration | | |
| Parity | | |
| Drift (only user-svc has this) | | |

## OpenAPI quality

- [ ] Every endpoint has `summary` + `description` + `tags`
- [ ] Every Pydantic field has a `description=`
- [ ] File-upload endpoints use `UploadFile = File(...)`
- [ ] Deprecated endpoints are marked `deprecated=True` with successor URL in description

## Open issues / deviations

| Issue | Disposition (e.g. "fix in Phase 4", "won't fix", "covered by ticket #...") |
|---|---|
| | |

## Approval

- [ ] All ported routes match the endpoint plan in PLAN.md
- [ ] OpenAPI quality bar (docs/OPENAPI_QUALITY.md) passes
- [ ] Integration tests pass against staging-DB
- [ ] Parity tests pass (or tolerated diffs documented above)
- [ ] Cross-schema drift test passes (user-svc only)
- [ ] **User approval to proceed to next service** ☐
