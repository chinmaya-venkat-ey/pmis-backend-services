# User Service Microservice Extraction — Overview

A high-level explanation of what we did and why. Aimed at a developer
or reviewer who wasn't part of the work but needs to understand the
architecture, the choices, and the current state.

---

## What we did

Extracted user management and authentication from the PMIS monolith
into a standalone microservice. Both services now run side by side,
share one Postgres database, and share a JWT signing key. A client
can authenticate against one service and have its token honoured by
the other — transparently, without any inter-service HTTP calls.

No monolith endpoint was removed. No user interaction with the system
changed. The monolith remains fully functional; the new service is
purely additive.

## Why we did it

- Auth and user management are cross-cutting concerns that don't
  belong entangled with business logic (projects, milestones, tasks).
- Once separated, a different team or release cadence can own it.
- It sets the template for future extractions (projects service,
  etc.) without having to reinvent the split pattern each time.
- It lets us scale or harden auth independently of the rest of PMIS
  in the future.

---

## What we built

A single new service: **`pmis-user-service`**. Self-contained — JWT
signing/verification, password hashing, RBAC, and the auth middleware
all live inside it. No external shared package; the service owns its
entire auth surface. Comes with its own Dockerfile and Docker Compose
file for local runs (DevOps owns multi-service orchestration in
production).

---

## How the two services coordinate

They don't, directly. They **share three things**, and that's enough.

- **Shared database.** One Postgres, one schema. The user-service
  owns writes to `users`, `roles`, and `revoked_tokens`. The
  monolith reads them for foreign-key lookups and session checks.

- **Shared signing key.** Both services load the same `SECRET_KEY`
  from their environment. The user-service signs a token; the
  monolith verifies the signature locally using the same algorithm
  (HS256). No HTTP round-trip to "validate" tokens — the math works
  offline. The two services do not share Python code; the JWT spec
  itself is the contract.

- **Shared blacklist.** When a user logs out on the user-service, it
  writes a row to `revoked_tokens`. On the next request, the
  monolith's auth middleware reads that table and rejects the token.
  Logout takes effect everywhere immediately, with no message bus
  and no cache invalidation.

The net result: the two services feel like one unified system from
the client's perspective, even though they're different processes
with different deploy cycles.

---

## Migration strategy — Strangler Fig

Both services serve the auth endpoints during the transition. The
monolith still has its full user module and keeps answering requests
on `:8000`. The new service also answers them on `:8001`. Clients
can hit either.

This gives us:
- **Zero downtime** during the migration.
- **Instant rollback** — if the new service misbehaves, stop it. The
  monolith keeps working.
- **A burn-in window** in production (suggested 2 weeks) to watch
  the new service at real traffic before committing to it.

Only after that burn-in do we remove the duplicate code from the
monolith. Until then, the new service is a live-tested redundancy.

---

## The work, in phases

1. **Scaffold the new service.** Empty FastAPI skeleton on port 8001.
   Wire it to the shared database with its own Alembic migration chain
   (kept independent from the monolith's via a separately-named
   version table in the same DB).

2. **Port the user module.** Models, repositories, security, RBAC,
   middleware, routes, controllers, services — moved from the
   monolith into the new service. The new service owns its own JWT
   and password code; cross-service compatibility is via shared env
   (`SECRET_KEY`), not shared code.

3. **Write an idempotent first migration.** The shared DB already
   has the user-related tables (created by the monolith long ago).
   The new service's migration checks table existence before creating
   — a no-op on the already-populated DB, a real create on a fresh
   DB.

4. **Write tests.** 35 tests covering user CRUD, login, logout,
   refresh rotation, RBAC gating. All passing.

5. **Verify cross-service auth manually.** Log in against the new
   service, use the token on the monolith — works. Log out against
   the new service, try the same token on the monolith — rejected.
   This proves the shared-secret and shared-blacklist designs work
   in practice.

6. **Containerize the new service.** A Dockerfile + a Docker Compose
   file inside this repo. `docker compose up` gives a production-like
   run locally.

---

## Key design choices and the rationale

| Choice | Why |
|---|---|
| Same database, same schema | The monolith has hard foreign keys from business entities to users. Splitting the database would drop referential integrity and add a sync layer we don't need yet. |
| Shared JWT secret instead of a remote `/verify` endpoint | An HTTP round-trip per authenticated request would add latency and a new failure mode. HS256 with a shared secret is the standard pattern and lets verification happen offline. |
| Separate Alembic version tables for the two services | Each service owns its migrations. No need to merge repos or coordinate releases. Well-established multi-service Alembic pattern. |
| Auth code self-contained in the service, not a shared library | Each service's auth needs are small enough to maintain independently. Cross-service compatibility is the JWT spec + shared secret, not shared Python code. Less infrastructure to maintain. |
| Strangler Fig migration, not hard cutover | Zero risk of breaking existing clients. Rollback is stopping the new service. A two-week burn-in observes real production traffic before we commit. |
| Docker Compose per service, not a centralized orchestration repo | Each service ships with its own dev/test compose. Production multi-service orchestration is owned by the DevOps engineer in their deployment configuration, separate from any service repo. |

---

## Current state

- Monolith still runs on port 8000. Unchanged user-facing behaviour.
- New user-service runs on port 8001, currently via Docker locally.
- Both share the same Postgres in WSL.
- Cross-service auth flows are verified end to end.
- The full test suite passes (35/35).

## What remains

- Push this service to GitHub.
- Deploy onto the production server alongside the monolith (DevOps).
- Observe production traffic for the burn-in period.
- After burn-in, remove the duplicate user module from the monolith
  and let this service be the sole owner of those endpoints.
