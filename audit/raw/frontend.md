# Frontend API Client Audit (READ-ONLY)

Scope: `C:\Programming\PMIS\PMIS-Frontend-OpenProject\` — API-client layer only.
Method: 13 files read (well under the ~30 cap). UI components, routing, and state stores were inspected only to the extent needed to confirm API call paths.

Legend: OBSERVED = direct code citation; INFERRED = reasonable deduction from observed code; [UNVERIFIED] = claim not confirmable from inspected files.

---

## 1. Tech & dependencies

- **React 19.2.4** — OBSERVED `C:\Programming\PMIS\PMIS-Frontend-OpenProject\package.json:14`
- **Build tool: Vite ^8.0.4** — OBSERVED `package.json:30`; scripts run `vite` / `vite build` (`package.json:7-11`)
- **Router: react-router-dom 7.14.1** — OBSERVED `package.json:18`
- **State lib: none** (no Redux, no Zustand, no React Query / RTK Query in `package.json:13-19`). INFERRED: app uses plain React hooks plus a small home-grown store at `src/store/project/uiStore.js` (referenced from `src\api\client.js:1`).
- **HTTP client: native `fetch` only.** No axios, no rtk-query in `package.json`. OBSERVED `fetch(` usage only in `src\api\client.js:173,253,263,302`. Every other module talks to the backend via the central `api.*` helper or `authorizedFetch` exported from `client.js`.
- Charts/icons: `recharts 3.8.1`, `react-icons 5.6.0` (`package.json:17,19`) — not relevant to API layer.

---

## 2. Base URL configuration

- **Single source of truth:** `src\api\client.js:3`
  ```
  const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://10.1.131.199:8000/';
  ```
  Normalized one line later (`client.js:7`) into the exported `API_BASE` constant (`RAW_BASE` with any trailing `/` stripped).
- **Env var driver:** `VITE_API_BASE_URL` (Vite-style). Defined in:
  - `C:\Programming\PMIS\PMIS-Frontend-OpenProject\.env.development:1` → `VITE_API_BASE_URL=http://10.1.131.199:8000`
  - Build-arg passthrough: `Dockerfile:14,19`
  - Runtime guard: `deploy.sh:49-50`, `start.sh:84-91`
- **vite.config.js has no proxy** (OBSERVED `vite.config.js:1-8` — minimal config, just `@vitejs/plugin-react`). So the browser hits the backend directly at the `VITE_API_BASE_URL` host:port.
- **Consume sites for `API_BASE`** (where the constant is template-literal'd onto an `ENDPOINTS.*` path):
  - `src\api\milestoneConfigApi.js:12` (helper `url(path)` at line 76-78)
  - `src\pages\projects\AddProjectPage.jsx:10` (lines 154, 207, 310)
  - `src\pages\projects\ProjectsListPage.jsx:8` (line 88)
  - `src\pages\projects\ProjectDetailsPage.jsx:14` (lines 202, 253, 300, 429, 460, 491)
  - `src\pages\users\UserDetails.jsx:7` (lines 137, 161)
  - `src\pages\users\UserForm.jsx:9` (lines 106, 131)
  - `src\pages\vendors\VendorDetails.jsx:9` (line 170)
  - `src\pages\vendors\VendorForm.jsx:7` (line 47)
- **`api.*` helper resolves URLs internally** via `BASE = RAW_BASE` (`client.js:9`) and `buildUrl()` (`client.js:209-214`). Callers pass `ENDPOINTS.x` paths only — the base is concatenated centrally.
- **`REFRESH_PATH` is hardcoded** at `client.js:10` as `/api/v3/users/refresh`. This is the only `/api/v3/*` literal outside `endpoint.js` that lives in active code (others are in comments only — see §3).
- **Hardcoded host/port search results** (`http://`, `localhost:`, `127.0.0.1`, `10.1.131`): only one in JS strings — the fallback URL at `client.js:3`. All other `http://` matches are SVG `xmlns` attributes or Google Fonts `@import`s — irrelevant.
- **Verdict on "one base URL" claim: TRUE.**
  - One environment variable (`VITE_API_BASE_URL`), one read site (`client.js:3`), one exported constant (`API_BASE` at `client.js:7`), one fallback literal (`client.js:3`).
  - Changing host/port for the entire frontend is a single env var change — no source edits required.
  - Caveat: this is "one base URL", NOT "one base URL + one path prefix". The `/api/v3` prefix is repeated 64 times inside `ENDPOINTS` literals in `src\api\endpoint.js:13-130`. See §6.

---

## 3. Path-construction pattern

- **Centralized endpoints map:** `src\api\endpoint.js` is the single registry. Comment at `endpoint.js:1-7` states verbatim: *"Single source of truth for every REST path the frontend calls."*
- **Two consumption styles** — both correct, both flow through the central map:
  1. **`api.*` style (preferred)** — pass an `ENDPOINTS.x` value; `request()` (`client.js:281-348`) prepends `BASE`. Used in `auth.js`, `projects.js`, `users.js`, `vendors.js`, `divisions.js`, `nodes.js`, `dashboard.js`.
     Example: `src\api\projects.js:17` — `api.get(ENDPOINTS.projects.list, { query: { offset, pageSize, active } });`
  2. **`authorizedFetch` style** — caller does `` `${API_BASE}${ENDPOINTS.x}` `` template-literal. Used by `milestoneConfigApi.js` and the listed pages in §2.
     Example: `src\pages\projects\ProjectsListPage.jsx:87-93`:
     ```
     const res = await authorizedFetch(
       `${API_BASE}${ENDPOINTS.projects.list}?offset=1&pageSize=100`,
       { method: "GET", headers: { accept: "application/json" } }
     );
     ```
- **No path literal is constructed inline anywhere.** Every `/api/v3/...` string in JS source lives in `endpoint.js`. Grep results confirm: matches outside `endpoint.js`, `client.js:10`, and `dashboard.js` (where `/api/v3` only appears in `/* ... */` doc comments) are all inside JSDoc/block comments — e.g. `pages\Dashboard.jsx:18,21,552`; `pages\projects\ProjectDetailsPage.jsx:194,242,339,407,455,486`; `pages\projects\MilestoneConfigPage.jsx:232,396`; `utils\project\milestoneConfigHelpers.js:313`; `api\users.js:75`; `api\milestoneConfigApi.js:220,245,334,431,788,844`. INFERRED: these comments are descriptive, not code paths.
- **Three sample calls from across the codebase:**
  1. Project list (preferred style) — `src\api\projects.js:16-21`:
     ```
     export async function list({ offset = 1, pageSize = 50, active } = {}) {
       const res = await api.get(ENDPOINTS.projects.list, {
         query: { offset, pageSize, active },
       });
       return unwrapList(res).map(fromApiProject);
     }
     ```
  2. Login (auth-disabled flag) — `src\api\auth.js:44-49`:
     ```
     const res = await api.post(
       ENDPOINTS.auth.login,
       { login, password },
       { auth: false }
     );
     ```
  3. Milestone tree fetch (template-literal style) — `src\api\milestoneConfigApi.js:435-437`:
     ```
     const raw = await apiGet(ENDPOINTS.projects.tree(projectId) + "?includeDeleted=false");
     ```
- **Sample 20 lines of the central map** (`src\api\endpoint.js:11-30`):
  ```
  export const ENDPOINTS = {
    auth: {
      login: '/api/v3/users/login',
      logout: '/api/v3/users/logout',
      me: '/api/v3/users/me',
      introspect: '/api/v3/users/introspect',
      refresh: '/api/v3/users/refresh',
      sendOtp: '/api/v3/users/login/send-otp',
      verifyOtp: '/api/v3/users/login/verify-otp',
      forgotPassword: '/api/v3/users/forgot-password',
      resetPassword: '/api/v3/users/reset-password',
    },
    users: {
      list: '/api/v3/users',
      get: (id) => `/api/v3/users/${enc(id)}`,
      create: '/api/v3/users/create',
      update: (id) => `/api/v3/users/${enc(id)}`,
      updatePassword: (id) => `/api/v3/users/${enc(id)}/password`,
      remove: (id) => `/api/v3/users/${enc(id)}`,
    },
  ```

---

## 4. Full call inventory

Compiled from `src\api\endpoint.js:11-132` plus the lone refresh-path constant. Distinct endpoints below = 64. Each row cites one representative caller (the map entry is reused by many callers across pages + per-resource modules).

| METHOD | PATH (as FE constructs it) | CALLER FILE:LINE (example) | PURPOSE |
|---|---|---|---|
| POST | `/api/v3/users/login` | `src\api\auth.js:46` | Username/password login (may require OTP) |
| POST | `/api/v3/users/logout` | `src\api\auth.js:107` | Logout |
| GET | `/api/v3/users/me` | `src\api\auth.js:98` | Current-user profile |
| POST | `/api/v3/users/introspect` | `src\api\auth.js:102` | Validate current token |
| POST | `/api/v3/users/refresh` | `src\api\client.js:163` | Refresh access token (also hardcoded as `REFRESH_PATH` at `client.js:10`) |
| POST | `/api/v3/users/login/send-otp` | `src\api\auth.js:66` | Send OTP for 2FA login |
| POST | `/api/v3/users/login/verify-otp` | `src\api\auth.js:74` | Verify OTP and complete login |
| POST | `/api/v3/users/forgot-password` | `src\api\auth.js:83` | Initiate password reset |
| POST | `/api/v3/users/reset-password` | `src\api\auth.js:91` | Complete password reset |
| GET | `/api/v3/users` | `src\api\users.js:61` | List users |
| GET | `/api/v3/users/{id}` | `src\api\users.js:66` | Get user by id |
| POST | `/api/v3/users/create` | `src\api\users.js:71` | Create user |
| PATCH | `/api/v3/users/{id}` | `src\api\users.js:105` | Update user |
| PATCH | `/api/v3/users/{id}/password` | `src\api\users.js:110` | Admin-set user password |
| DELETE | `/api/v3/users/{id}` | `src\api\users.js:114` | Delete user |
| GET | `/api/v3/vendors` | `src\api\vendors.js:109` | List vendors |
| GET | `/api/v3/vendors/{id}` | `src\api\vendors.js:114` | Get vendor by id |
| POST | `/api/v3/vendors/create` | `src\api\vendors.js:127` | Create vendor |
| PATCH | `/api/v3/vendors/{id}` | `src\api\vendors.js:180` | Update vendor + user_assignments |
| DELETE | `/api/v3/vendors/{id}` | `src\api\vendors.js:185` | Delete vendor |
| GET | `/api/v3/divisions` | `src\pages\projects\ProjectDetailsPage.jsx:253` | List divisions (UI dropdown) |
| GET | `/api/v3/master/divisions` | `src\api\divisions.js:35` | Master division list |
| POST | `/api/v3/master/divisions/create` | `src\api\divisions.js:40` | Create master division |
| PATCH | `/api/v3/master/divisions/{code}` | `src\api\divisions.js:52` | Update master division |
| DELETE | `/api/v3/master/divisions/{code}` | `src\api\divisions.js:57` | Delete master division |
| POST | `/api/v3/master/divisions/{code}/restore` | `src\api\divisions.js:61` | Restore soft-deleted division |
| GET | `/api/v3/master/roles` | `src\api\endpoint.js:63` | List roles [UNVERIFIED] — only declared in map; no observed caller in inspected files |
| GET | `/api/v3/resource_types` | `src\api\milestoneConfigApi.js:385` | Resource-type dropdown |
| GET | `/api/v3/priorities` | `src\api\milestoneConfigApi.js:411` | Priority dropdown |
| GET | `/api/v3/projects` | `src\api\projects.js:17` | List projects |
| GET | `/api/v3/projects/{uuid}` | `src\api\projects.js:24` | Get project |
| GET | `/api/v3/projects/{uuid}/tree` | `src\api\projects.js:29`; `src\api\milestoneConfigApi.js:437` | Full M→A→T→ST tree |
| POST | `/api/v3/projects/create` | `src\pages\projects\AddProjectPage.jsx:310` (via `ENDPOINTS.projects.create`) | Create project |
| PATCH | `/api/v3/projects/{uuid}` | `src\api\projects.js:39` | Update project |
| DELETE | `/api/v3/projects/{uuid}` | `src\api\projects.js:56` | Delete project |
| POST | `/api/v3/projects/{uuid}/save` | `src\api\projects.js:44`; `src\api\milestoneConfigApi.js:472` | Save draft |
| POST | `/api/v3/projects/{uuid}/publish` | `src\api\projects.js:48` | Publish project |
| POST | `/api/v3/projects/{uuid}/close` | `src\api\projects.js:52` | Close project |
| GET | `/api/v3/projects/{uuid}/milestones` | `src\api\milestoneConfigApi.js:449,478` | List milestones for project |
| POST | `/api/v3/projects/{uuid}/milestones/create` | `src\api\nodes.js:98`; `src\api\milestoneConfigApi.js:562` | Create milestone |
| PATCH | `/api/v3/milestones/{id}` | `src\api\nodes.js:109`; `src\api\milestoneConfigApi.js:578` | Update milestone |
| DELETE | `/api/v3/milestones/{id}` | `src\api\nodes.js:113`; `src\api\milestoneConfigApi.js:590` | Delete milestone |
| GET | `/api/v3/milestones/{id}/activities` | `src\api\milestoneConfigApi.js:597` | List activities for milestone |
| GET | `/api/v3/milestones/{id}/attachments` | `src\api\endpoint.js:84` | List milestone attachments [UNVERIFIED] — declared in map; not observed used in the 13 files inspected |
| GET | `/api/v3/milestones/{id}/comments` | `src\api\milestoneConfigApi.js:572,582` | List/post milestone comments + attachments |
| POST | `/api/v3/milestones/{id}/activities/create` | `src\api\nodes.js:119`; `src\api\milestoneConfigApi.js:616` | Create activity under milestone |
| GET | `/api/v3/activities/{id}` | `src\api\milestoneConfigApi.js:605` | Get activity |
| PATCH | `/api/v3/activities/{id}` | `src\api\nodes.js:131`; `src\api\milestoneConfigApi.js:653` | Update activity |
| DELETE | `/api/v3/activities/{id}` | `src\api\nodes.js:137`; `src\api\milestoneConfigApi.js:665` | Delete activity |
| GET | `/api/v3/activities/{id}/tasks` | `src\api\milestoneConfigApi.js:672` | List tasks for activity |
| POST | `/api/v3/activities/{id}/tasks/create` | `src\api\nodes.js:143`; `src\api\milestoneConfigApi.js:697` | Create task under activity |
| GET | `/api/v3/activities/{id}/attachments` | `src\api\endpoint.js:98` | Activity attachments [UNVERIFIED] — declared, no caller observed |
| GET | `/api/v3/activities/{id}/comments` | `src\api\milestoneConfigApi.js:629,657` | List/post activity comments |
| GET | `/api/v3/tasks/{id}` | `src\api\milestoneConfigApi.js:678` | Get task |
| PATCH | `/api/v3/tasks/{id}` | `src\api\nodes.js:154`; `src\api\milestoneConfigApi.js:714` | Update task |
| DELETE | `/api/v3/tasks/{id}` | `src\api\nodes.js:158`; `src\api\milestoneConfigApi.js:726` | Delete task |
| GET | `/api/v3/tasks/{id}/subtasks` | `src\api\milestoneConfigApi.js:796` | List subtasks for task (flat-with-parent) |
| POST | `/api/v3/tasks/{id}/subtasks/create` | `src\api\nodes.js:165`; `src\api\milestoneConfigApi.js:880` | Create subtask under task |
| GET | `/api/v3/tasks/{id}/attachments` | `src\api\endpoint.js:108` | Task attachments [UNVERIFIED] — declared, no caller observed |
| GET | `/api/v3/tasks/{id}/comments` | `src\api\milestoneConfigApi.js:700,718` | List/post task comments |
| GET | `/api/v3/subtasks/{id}` | `src\api\milestoneConfigApi.js:839,853` | Get subtask (also returns nested children) |
| PATCH | `/api/v3/subtasks/{id}` | `src\api\nodes.js:175`; `src\api\milestoneConfigApi.js:896` | Update subtask |
| DELETE | `/api/v3/subtasks/{id}` | `src\api\nodes.js:179`; `src\api\milestoneConfigApi.js:908` | Delete subtask |
| GET | `/api/v3/subtasks/{id}/subtasks` | `src\api\milestoneConfigApi.js:832` | List children of a subtask (rarely used; preferred is task-level tree) |
| POST | `/api/v3/subtasks/{id}/subtasks/create` | `src\api\nodes.js:164`; `src\api\milestoneConfigApi.js:879` | Create nested subtask |
| GET | `/api/v3/subtasks/{id}/attachments` | `src\api\endpoint.js:118` | Subtask attachments [UNVERIFIED] — declared, no caller observed |
| GET | `/api/v3/subtasks/{id}/comments` | `src\api\milestoneConfigApi.js:882,900` | List/post subtask comments |
| GET | `/api/v3/dashboard/summary` | `src\api\dashboard.js:40` | Admin dashboard summary KPIs |
| GET | `/api/v3/dashboard/projects` | `src\api\dashboard.js:54` | Dashboard project cards |
| GET | `/api/v3/dashboard/projects/{uuid}` | `src\api\dashboard.js:61` | Dashboard single project detail |
| GET | `/api/v3/dashboard/projects/{uuid}/items` | `src\api\dashboard.js:68` | Dashboard project items (milestones/activities) |
| GET | `/api/v3/dashboard/organisations` | `src\api\dashboard.js:75` | Dashboard org list |
| GET | `/api/v3/dashboard/organisations/{vendorId}` | `src\api\dashboard.js:80` | Dashboard single org detail |

**Total distinct endpoints in the FE map: 64** (every entry in `src\api\endpoint.js:11-130` plus the duplicate `REFRESH_PATH` literal at `client.js:10`, which targets the same `/api/v3/users/refresh` already declared as `ENDPOINTS.auth.refresh`).

**Endpoints declared in map but with no caller found in the 13 files inspected (5)** — INFERRED: these may be wired into UI files not in the API folder (likely the Comments/Attachments panel components), or may be dead. Treat as `[UNVERIFIED]` until a wider grep of `components/`:
- `ENDPOINTS.milestones.attachments` (`endpoint.js:84`)
- `ENDPOINTS.activities.attachments` (`endpoint.js:98`)
- `ENDPOINTS.tasks.attachments` (`endpoint.js:108`)
- `ENDPOINTS.subtasks.attachments` (`endpoint.js:118`)
- `ENDPOINTS.roles.list` (`endpoint.js:63`)
The `uploadFile` helper in `milestoneConfigApi.js:224-236` is defined but never called from within that file — INFERRED: invoked from a component, or dead code.

---

## 5. Auth handling on FE

- **Token storage: dual — sessionStorage + localStorage, with legacy keys mirrored.** OBSERVED `src\api\client.js:41-103` (`tokenStore` object).
  - Modern keys (`pmis_token`, `pmis_refresh_token`, `pmis_user`, `pmis_access_expires_at`) at `client.js:12-15`
  - Legacy keys (`auth_token`, `auth_refresh_token`, `auth_user`) at `client.js:19-21`
  - Reads: session-first, then local, then legacy (`client.js:42-46`, `66-70`, `76-81`)
  - Writes: every set hits all three locations (`client.js:47-51`, `71-75`, `83-89`)
  - INFERRED: dual-write is to preserve cross-tab sessions while still cleaning up legacy storage on logout.
- **Token attachment: centralized in two helpers in `client.js`.**
  - `mergeHeadersWithToken(initHeaders, token)` at `client.js:216-238` strips any caller-supplied `Authorization` and writes a fresh `Bearer ${token}`, plus `Accept`/`Cache-Control`/`Pragma` defaults.
  - `authorizedFetch(input, init)` at `client.js:244-279` is the `fetch` wrapper used by `milestoneConfigApi.js` and the pages listed in §2.
  - `request(method, path, opts)` at `client.js:281-348` is the `api.*` body that wraps the second style; it injects the bearer via `buildHeaders(token)` at `client.js:289-300`.
  - There is **no axios interceptor** — there is no axios. The two helpers above are functionally equivalent to an interceptor.
- **Refresh logic: single-flight, automatic, on 401.** OBSERVED `client.js:154-207` (`refreshAccessToken`):
  - `refreshInFlight` (`client.js:154`) deduplicates parallel 401s to one `/refresh` call.
  - `POST /api/v3/users/refresh` body `{ refresh_token: <stored> }`, plus the stale access token as `Authorization: Bearer ...` (`client.js:166-176`).
  - On success, updates `tokenStore` with both tokens, the user object, and `expiresAt` (`client.js:189-198`).
  - On 401 from `/refresh` itself, clears tokens to avoid an infinite loop (`client.js:178-186`).
  - `authorizedFetch` retries the original request once with the new token at `client.js:255-264`. `request` does the same at `client.js:312-315`.
  - If the retry still 401s, `notifyAuthError(...)` at `client.js:132-151` clears tokens, fires one popup via `uiStore.showError`, then redirects to `/login`.
- **Idle-timeout watchdog** at `src\api\sessionManager.js`. Custom `useSessionManager()` React hook (`sessionManager.js:56-135`):
  - 15-minute inactivity ceiling (`sessionManager.js:20`), tracked via `mousemove`/`keydown`/etc.
  - Pro-active refresh ~60 s before `expiresAt`, or every 12 min as fallback (`sessionManager.js:21-22`, `91-124`).
  - On idle expiry, calls `logout()` and pops a `uiStore.showMessage` → `/login` redirect (`sessionManager.js:81-89`).
- **Session-reset broadcast**: `notifySessionReset()` at `client.js:35-39` fires a `pmis:session-reset` `CustomEvent` on login + logout, so caches (DataContext, projectsStore, draftStore, uiStore) drop stale user data before User B fetches. INFERRED: keeps multi-user-on-one-machine flows clean.
- **`auth.js` is a thin adapter** over `api.*` + `tokenStore` (`src\api\auth.js:1-144`). It also mirror-writes legacy keys (`auth_token` etc.) for backward compatibility (`auth.js:21-30`).

---

## 6. Risks / open questions for refactor

### Verdict on the user's claim

The user said the FE uses "a single base URL + one port, so changing `/api/v3/*` to `/<service>/*` is supposedly a one-line FE config change."

- **Base URL: TRUE — single env-var change**, no source edit needed:
  - Set `VITE_API_BASE_URL=<new host:port>` in `.env.development` (`C:\Programming\PMIS\PMIS-Frontend-OpenProject\.env.development:1`) and rebuild. That's it.
- **Path prefix `/api/v3` → `/<service>/*`: NOT a one-liner.** The prefix is repeated literally **64 times** as a string inside `src\api\endpoint.js:13-130` (plus once at `client.js:10` for `REFRESH_PATH`). It is NOT extracted into a constant.

The refactor scenario is a path-rewrite, not a base-URL swap. Two viable approaches:

1. **Edit `endpoint.js` only — one file, ~64 lines.** Either:
   - Sed-style replace per service (e.g. `/api/v3/users/...` → `/users/.../api/v3/users/...` or `/identity/api/v3/users/...`). Trivial since literals are flat strings inside an object literal.
   - Introduce a `const PREFIX = '/api/v3'` (or per-service map) at the top, template-literal'd into each entry. Safest long-term but more lines to touch.
   - Also patch `client.js:10` `REFRESH_PATH` — it's a duplicate of `ENDPOINTS.auth.refresh` and should be replaced by importing the latter (or itself prefixed if you stay literal).
2. **API gateway / reverse-proxy strategy: zero FE code changes.** The single base URL points at a gateway; the gateway rewrites `/api/v3/users/*` → user-service, `/api/v3/projects/*` → project-service, etc. Backwards-compatible with all 64 paths.

### Dynamic path construction — find-replace resistance

- All dynamic segments use template literals with single-call `enc()` (= `encodeURIComponent`) wrappers, e.g. `` (id) => `/api/v3/users/${enc(id)}` ``. The `/api/v3` substring is always **literal** and **leading** within the template. A naive `sed 's|/api/v3/|/svc/|g'` on `endpoint.js` works.
- **Two exceptions** that templated extension onto an endpoint result:
  - `src\api\milestoneConfigApi.js:437`: `ENDPOINTS.projects.tree(projectId) + "?includeDeleted=false"` — query string appended; safe.
  - `src\api\milestoneConfigApi.js:597,672,796,832`: `... + LIST_QS` where `LIST_QS = "?offset=1&pageSize=20&includeDeleted=false"` (`milestoneConfigApi.js:29`). All append-only; do not affect prefix.
- **Page-level template-literal pattern is robust**: e.g. `` `${API_BASE}${ENDPOINTS.projects.list}?offset=1&pageSize=100` `` — `ENDPOINTS.x` is still the central source, so a one-shot change to `endpoint.js` propagates to every call site automatically.

### Hardcoded-path inventory (paths outside the central map)

Active code (NOT inside a `//` or `/* */` comment):

| File:line | Value | Notes |
|---|---|---|
| `src\api\client.js:3` | `'http://10.1.131.199:8000/'` | Fallback when `VITE_API_BASE_URL` is unset — host/port literal, not a path prefix |
| `src\api\client.js:10` | `'/api/v3/users/refresh'` | `REFRESH_PATH` constant — duplicates `ENDPOINTS.auth.refresh`. Should be deduplicated during the refactor. |
| `src\api\endpoint.js:13-130` | 64 × `/api/v3/...` literals | Central map — intended single source. Where the refactor work lives. |

All `/api/v3` occurrences in `src\pages\**`, `src\components\**`, `src\utils\**` are inside JSDoc/block-comment text, NOT live code (verified via grep — see §3 above).

### Other observations relevant to the refactor

- **No service worker, no client-side cache** that would hold onto old paths (cache-busting via `Cache-Control: no-cache` and `cache: 'no-store'` at `client.js:229-236, 248, 293-296, 306`).
- **No path-versioning logic on the FE** — there is no `apiVersion` switch. If `/api/v3` becomes `/api/v4` for one service, that's still a per-line edit in `endpoint.js`.
- **`endpoint.js` declares 5 endpoints with no observed caller** (see §4 last bullet). INFERRED: candidates for follow-up grep over `components/`. If still unused, the corresponding BE routes are candidates for the user's "delete-deprecated" pass — but confirm before deleting; the attachments paths are very likely live (uploadFile exists in `milestoneConfigApi.js:224-236`, just not called from that file).
- **`introspect` endpoint is defined and `me()` calls it** — `src\api\auth.js:101-103`. Both `/api/v3/users/me` (GET) and `/api/v3/users/introspect` (POST) are wired; INFERRED redundant — possible candidate for BE consolidation, but harmless for refactor.
- **The frontend is read-only for the refactor (per user)** — this is consistent with the design: a path-prefix change in `endpoint.js` (~1 PR, ≤1 file changed) or a gateway-based rewrite (zero PRs) are both viable without disturbing UI components.

### Open questions for the refactor lead

1. Will the new architecture preserve `/api/v3` and only segment by sub-path, or rename to `/users/...`, `/projects/...`, etc.? Either way the FE work is bounded to `endpoint.js` + `client.js:10`.
2. Are the 5 unobserved endpoints (4 × attachments + roles.list) actually used anywhere outside the inspected files? Suggest one wider grep over `src/components/**` and `src/pages/**` for `ENDPOINTS.<name>.attachments` and `ENDPOINTS.roles` before declaring them dead.
3. The `REFRESH_PATH` duplication (`client.js:10` vs `endpoint.js:17`) is a latent maintenance hazard during the refactor — if the path moves, both must move. Recommend `import { ENDPOINTS } from './endpoint';` inside `client.js` and dropping `REFRESH_PATH`. (Care needed re: import order — `endpoint.js` is a tiny pure-data module so it should be safe.)
4. Confirm whether the `recharts`-driven Dashboard makes any direct API calls not routed through `dashboard.js` — likely no (the file imports only from `../api/dashboard`), but a 5-file spot-check of `pages\Dashboard.jsx` would close the loop. [UNVERIFIED]
