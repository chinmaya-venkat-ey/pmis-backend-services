# PMIS Refactor

In-progress refactor of PMIS from a monolith + partial-extraction microservices into four clean services behind nginx.

## Documents

- [REFACTOR_DECISIONS.md](REFACTOR_DECISIONS.md) — Phase 0 alignment + Checkpoint 2 reconciliation (Q&A locked)
- [AUDIT.md](AUDIT.md) — Phase 1 audit (frozen at Checkpoint 2)
- [PLAN.md](PLAN.md) — Phase 2 plan (current)
- [docs/MIGRATION_GUIDE.md](docs/MIGRATION_GUIDE.md) — operator how-to for the cutover
- [docs/DEPLOY_GUIDE.md](docs/DEPLOY_GUIDE.md) — illustrative deploy reference (devops adapts)
- [docs/CUTOVER_RUNBOOK.md](docs/CUTOVER_RUNBOOK.md) — step-by-step maintenance-window script
- [docs/OPENAPI_QUALITY.md](docs/OPENAPI_QUALITY.md) — Swagger doc quality bar enforced in Phase 3
- [audit/raw/](audit/raw/) — per-repo Phase 1 raw reports (with `path:line` citations)

## Services

| Service | Container internal port | URL prefix | Owns schema |
|---|---:|---|---|
| `pmis-user-management` | 8001 | `/user/*` | `users` |
| `pmis-project-management` | 8003 | `/project/*` | `project` |
| `pmis-notification-management` | 8002 | `/notification/*` | (none — stateless dispatcher) |
| `pmis-masters-management` | 8004 | `/masters/*` | `masters` |
| `pmis-frontend` | 3000 | `/` | — |

All requests reach a service via nginx (illustrative config in [nginx/](nginx/); devops owns production-shape).

## Source repos (READ-ONLY for this refactor)

- `C:\Programming\PMIS\PMIS-OpenProject` — current monolith
- `C:\Programming\PMIS\PMIS-user-management` — partial extraction (user/auth)
- `C:\Programming\PMIS\PMIS-notification-service` — partial extraction (dispatch)
- `C:\Programming\PMIS\PMIS-project-management` — partial extraction (project domain)
- `C:\Programming\PMIS\PMIS-Frontend-OpenProject` — frontend (NEVER MODIFIED)

## Running locally

```bash
docker compose up
```

Brings up Postgres 16 + 4 backend services + frontend behind nginx on port 80. See [docs/DEPLOY_GUIDE.md](docs/DEPLOY_GUIDE.md) for the full env-var matrix.

## Phase 3 implementation order (gated)

1. `pmis-notification-management` (in progress — zero owned tables, simplest)
2. `pmis-masters-management`
3. `pmis-user-management`
4. `pmis-project-management`

Each service is presented for user approval (via its `MIGRATION_LOG.md`) before the next begins.
