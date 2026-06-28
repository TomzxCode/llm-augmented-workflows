---
issue: "#16"
title: "Client/Server architecture"
status: in-review
revision: 5
---

# Specification: Client/Server architecture

## Overview

Replace GitHub Actions as the execution substrate with a hosted HTTP server that receives GitHub webhook events, verifies HMAC-SHA256 payload signatures, loads persistent session state from SQLite, and dispatches events through the existing agent pipeline (refactored to accept context as function parameters). The server is a single Docker container with FastAPI + Uvicorn exposing a webhook receiver and a health-check endpoint. Session state is persisted to SQLite on a Docker volume for crash recovery. The existing CLI/CLI-workflow path is preserved and unchanged; repositories choose one deployment model.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Docker Container                             │
│                                                                      │
│  ┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐  │
│  │  Uvicorn     │────▶│  FastAPI App     │────▶│  Middleware       │  │
│  │  (ASGI)      │     │                  │     │  - Raw body       │  │
│  │              │     │  /webhook (POST) │     │  - Structured log │  │
│  │              │     │  /health   (GET) │     └──────────────────┘  │
│  └──────────────┘     └──────────────────┘              │            │
│                                                         ▼            │
│                                              ┌────────────────────┐  │
│                                              │ HMAC Verifier      │  │
│                                              │ (stdlib hmac)      │  │
│                                              └────────────────────┘  │
│                                                         │            │
│                                                         ▼            │
│                                              ┌────────────────────┐  │
│                                              │ Webhook Router     │  │
│                                              │ (delivery dedup)   │  │
│                                              └────────────────────┘  │
│                                                         │            │
│                                              ┌─────────┴──────────┐ │
│                                              │ Session Store      │ │
│                                              │ (aiosqlite + WAL)  │ │
│                                              └────────────────────┘ │
│                                                         │            │
│                                              ┌─────────┴──────────┐ │
│                                              │ Pipeline Bridge    │ │
│                                              │ (run_in_executor)  │ │
│                                              └────────────────────┘ │
│                                                         │            │
│                                              ┌─────────┴──────────┐ │
│                                              │ Existing Engine    │ │
│                                              │ (engine.py + route │ │
│                                              │  + run_rule +      │ │
│                                              │  run_steps +       │ │
│                                              │  apply_outcome)    │ │
│                                              └────────────────────┘ │
│                                                         │            │
│                                              ┌─────────┴──────────┐ │
│                                              │ Subprocess Calls   │ │
│                                              │ gh CLI │ opencode  │ │
│                                              └────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘

                   GitHub Webhooks ────▶ Port 8080
                   Admin API      ────▶ Port 8080
                   Health Check   ────▶ Port 8080
```

## Data Models

### `repositories`

| Field | Type | Constraints | Description |
|---|---|---|---|
| id | uuid | PK, not null | Internal identifier |
| owner | text | not null, unique with repo | GitHub owner (org or user) |
| repo | text | not null, unique with owner | GitHub repository name |
| secret_token | text | not null | HMAC-SHA256 secret for webhook verification |
| gh_token | text | not null | GitHub installation token or PAT for outbound API calls |
| active | boolean | not null, default true | Whether the server processes events for this repo |
| version | text | not null, default "v1" | Reserved for canary deployments (FR-10) |
| created_at | datetime | not null | ISO 8601 |
| updated_at | datetime | not null | ISO 8601 |
| metadata | json | nullable | Extension fields (unknown keys preserved, never rejected) |

The `gh_token` field stores sensitive GitHub credentials. At rest, the value is encrypted using AES-256-GCM with a key derived from the `TOKEN_ENCRYPTION_KEY` environment variable via HKDF. The encryption is transparent to application code: the session store encrypts on write and decrypts on read. If `TOKEN_ENCRYPTION_KEY` is not set, the server logs a warning at startup and stores tokens in plaintext (acceptable for development; production deployments must set this variable).

**Required GitHub token scopes:** The `gh_token` must include the following scopes to power the agent pipeline's outbound API calls via the `gh` CLI:
- `issues:write` — create and edit issues, post issue comments
- `pull_requests:write` — create and edit pull requests, post PR comments and reviews
- `contents:write` — create commits and push branches (for automated fix branches)
- `metadata:read` — read repository metadata (always included with any fine-grained token)

**Key rotation procedure:** To rotate the encryption key, the operator provides both `TOKEN_ENCRYPTION_KEY_OLD` (the current key) and `TOKEN_ENCRYPTION_KEY` (the new key) as environment variables at startup. The server reads every token from the database, decrypts with `TOKEN_ENCRYPTION_KEY_OLD`, re-encrypts with `TOKEN_ENCRYPTION_KEY`, and writes the updated ciphertext. After a successful rotation, `TOKEN_ENCRYPTION_KEY_OLD` is unset and only `TOKEN_ENCRYPTION_KEY` is retained. If `TOKEN_ENCRYPTION_KEY_OLD` is not set (absent from the environment, not empty), a normal startup proceeds (existing tokens are decrypted with `TOKEN_ENCRYPTION_KEY`).

**Bulk token re-encryption behavior:** Re-encryption at startup processes rows in batches of 100, logging progress after each batch (e.g., `"Re-encrypted 800/1200 tokens"`). A per-row error (e.g., corrupt ciphertext) logs the row ID and skips that row; the server continues startup without failing. The entire re-encryption is subject to a startup timeout of 30 seconds (configurable via `TOKEN_ENCRYPTION_TIMEOUT_SECONDS`). If the timeout is reached before all rows are processed, the server logs the count of remaining rows, skips re-encryption for those rows (existing tokens remain decryptable by `TOKEN_ENCRYPTION_KEY_OLD`), and proceeds to serve requests. A separate maintenance command (`llmaw-admin reencrypt-tokens`) can be invoked at runtime to complete the remaining rows without a restart.

**Migration from plaintext to encryption:** When `TOKEN_ENCRYPTION_KEY` is first set after a period of running without it, the server re-encrypts all plaintext tokens on startup. A separate offline tool (`llmaw-admin decrypt-tokens`) is provided for development and disaster recovery scenarios that require plaintext tokens. This command must be run against a stopped server instance and logs a warning before proceeding. Production deployments should always set `TOKEN_ENCRYPTION_KEY`.

Consumers must ignore unknown fields in response payloads. The `metadata` column exists for forward-compatible addition of backend-specific configuration without schema migration.

### `sessions`

| Field | Type | Constraints | Description |
|---|---|---|---|
| id | uuid | PK, not null | Internal identifier |
| repo_id | uuid | FK → repositories.id, not null | Owning repository |
| subject_type | text | not null | "issue", "pull_request", or "push" |
| subject_id | integer | not null | GitHub issue/PR number (0 for push events) |
| conversation_history | json | not null | Agent conversation history (list of message objects) |
| context | json | not null | Per-subject context (matched rules, current step state) |
| created_at | datetime | not null | ISO 8601 |
| updated_at | datetime | not null | ISO 8601 |
| version | integer | not null, default 1 | Optimistic concurrency counter, incremented on write |

Sessions are keyed by `(repo_id, subject_type, subject_id)`. The `subject_type` field is populated from the webhook event as follows:
- `issue_comment` and `issues` events map to `subject_type="issue"` with `subject_id` set to the issue number from the event payload.
- `pull_request` events map to `subject_type="pull_request"` with `subject_id` set to the PR number.
- `push` events map to `subject_type="push"` with `subject_id` set to `0` (there is no issue/PR number for push events).

This mapping ensures that all comments on the same issue share a single session, preserving conversation history across sequential `issue_comment` events (FR-02).

The `conversation_history` field stores the agent's conversation as a JSON array; each entry has `role` (user/assistant/system), `content`, and `timestamp`. The `context` field stores pipeline state. Consumers must preserve unknown fields in both JSON columns across read-write cycles (read-modify-write must retain unrecognized keys).

**Foreign key behavior:** The `repo_id` foreign key from `sessions` references `repositories.id` with `ON DELETE CASCADE` — when a repository is deregistered, its sessions are deleted automatically. The `webhook_events` table also has `ON DELETE CASCADE` from `repo_id` to `repositories.id`. This ensures no orphaned data remains after deregistration and keeps the session reaper's query logic simple (it only needs a `updated_at` filter).

**Session expiry and cleanup:** Sessions expire after 7 days of inactivity (no new webhook events for that `(repo_id, subject_type, subject_id)` key). Expiry is checked at every session load: before returning a session, the server compares `updated_at` against `SESSION_TTL_HOURS` (configurable, default 168). If the session has expired, a fresh empty session is created and the stale row is deleted. This load-time check is independent of the background reaper, which runs every hour and deletes all rows whose `updated_at` is older than the TTL. The reaper logs its deletion count and skips if database contention is detected (SQLITE_BUSY). Session count is tracked in the `/health` endpoint as active (non-expired) sessions. The `SESSIONS_MAX_AGE_HOURS` environment variable overrides the default TTL.

**Version change behavior:** When a repository's `version` is changed, existing sessions are NOT automatically reset — the existing conversation history and context may contain fields or formats from the previous version's configuration. The v1 config bundle tolerates unknown JSON fields in `conversation_history` and `context` (per the forward-compatibility policy). If a version rollback produces incompatible session data, the operator should deregister and re-register the repository, or manually delete the session rows in SQLite. A future version may add an admin endpoint to reset sessions on version change.

The `repositories.version` field supports canary deployments (FR-10) by selecting runtime configuration variants within a single container. The server maintains a mapping from version strings (e.g., `"v1"`, `"v2-canary"`) to agent configuration bundles: model identifier, system prompt template path, skill repository reference, and maximum iteration count. When processing a webhook for a repository with `version: "v2-canary"`, the server selects the `v2-canary` config bundle. All versions share the same engine code and binary; only the configuration differs. The set of available versions is defined in a YAML file mounted into the container (`/etc/llmaw/versions.yaml`), and the default version (`"v1"`) is always present. This approach satisfies multi-version support within NFR-07's single-container constraint. Future growth to separate binaries would require breaking NFR-07 or switching to a sidecar model.

**`versions.yaml` schema:**

```yaml
# /etc/llmaw/versions.yaml — defines available agent configuration bundles
# The "v1" version must always be present and acts as the default.
# Unknown fields in any version block are accepted and ignored (forward compat).
versions:
  v1:
    model: "gpt-4o"              # Model identifier passed to opencode CLI
    system_prompt: "/etc/llmaw/prompts/default.md"  # Path to system prompt template
    skill_repository: "https://github.com/org/skills.git"  # Git URL of skills repo
    skill_ref: "main"            # Git branch, tag, or commit SHA
    max_iterations: 10           # Maximum continuous chaining iterations
    metadata: {}                 # Reserved for version-specific extensions
  v2-canary:
    model: "gpt-4.1"
    system_prompt: "/etc/llmaw/prompts/canary.md"
    skill_repository: "https://github.com/org/skills.git"
    skill_ref: "canary"
    max_iterations: 15
    metadata: {}
```

The `versions.yaml` file is read at server startup during the initialization phase, before the health endpoint reports healthy. If the file is missing or malformed, the server logs a fatal error and exits. Each field within a version block is optional; missing fields fall back to the `v1` defaults. The `metadata` field provides a forward-compatible extension point for version-specific configuration that does not yet have a dedicated field. The set of available versions is cached in memory for the lifetime of the process; a server restart is required to pick up changes to the file.

**Version removal handling:** If a repository's `version` references a version key that no longer exists in `versions.yaml` (e.g., the key was removed during a deployment), the server falls back to the `v1` defaults for that repository, logs a warning with the missing version name and the repository identity, and continues startup. This prevents a crash loop for repositories that were configured with a now-removed version. The fallback is applied once at startup; an operator can then update the repository's `version` via the admin API.

### `webhook_events`

| Field | Type | Constraints | Description |
|---|---|---|---|
| id | uuid | PK, not null | Internal identifier |
| repo_id | uuid | FK → repositories.id, not null | Target repository |
| delivery_id | text | not null, unique | `X-GitHub-Delivery` header value |
| event_type | text | not null | e.g., "push", "pull_request", "issues" |
| payload | json | not null | Full webhook payload |
| hmac_valid | boolean | not null | Whether HMAC signature was verified |
| status | text | not null, default "received" | "received", "processing", "completed", "failed", "skipped" (dedup) |
| error | text | nullable | Error message if processing failed |
| created_at | datetime | not null | ISO 8601 |

The `webhook_events` table serves as an idempotency log and audit trail. The `delivery_id` unique constraint prevents duplicate processing when GitHub retries delivery. `status` is an open enum — consumers must handle unknown values gracefully by treating them as informational without breaking. New enum values are additive only; no existing value is removed without a major API version bump and at least one release cycle of deprecation notice.

**Event retention:** Webhook event rows are retained for 90 days (configurable via `EVENTS_RETENTION_DAYS` environment variable). A background cleanup task runs daily at midnight (server time) and deletes rows where `created_at` is older than the retention window. This prevents unbounded growth of the `webhook_events` table while keeping the audit trail accessible for a full quarter. Admin API queries that include a `created_at` filter are scoped by the database query (no additional filtering needed).

### Indexes

The following indexes are created at schema initialization to ensure lookup performance (NFR-03, NFR-04):

| Index | On | Columns | Purpose |
|---|---|---|---|
| idx_repositories_owner_repo | repositories | (owner, repo) | Lookup repository by webhook event owner/repo |
| idx_sessions_repo_subject | sessions | (repo_id, subject_type, subject_id) | Restore session on webhook event |
| idx_sessions_updated_at | sessions | (updated_at) | Session expiry reaper query |
| idx_webhook_events_delivery_id | webhook_events | (delivery_id) | Idempotency dedup lookup |
| idx_webhook_events_created_at | webhook_events | (created_at) | Event retention cleanup and admin API queries |
| idx_webhook_events_repo_id_status | webhook_events | (repo_id, status) | Admin API event listing by repo/status |

## API Contracts

All endpoints documented with unversioned paths (e.g., `POST /webhook`) are also available at their versioned equivalents (`POST /v1/webhook`) through dual route registration at server startup. The unversioned paths always resolve to the latest stable major version and are the canonical form for the current API major version. Future major versions (e.g., `/v2/webhook`) may introduce breaking changes; the unversioned alias will be updated to track the latest stable version. Deprecated versions are removed after at least one release cycle of deprecation notice.

### POST /webhook

Accepts GitHub webhook deliveries. The request body is the raw webhook payload; signature verification uses the `X-Hub-Signature-256` header.

**Request Headers**

| Header | Required | Description |
|---|---|---|
| X-Hub-Signature-256 | Yes | HMAC-SHA256 of the raw body, hex-encoded |
| X-GitHub-Delivery | Yes | Unique delivery identifier for idempotency |
| X-GitHub-Event | Yes | Event type (e.g., push, pull_request) |
| Content-Type | Yes | Must be application/json |

**Request Body**

Arbitrary JSON payload from GitHub. The server does not validate the payload schema beyond valid JSON — unknown fields are accepted and preserved in the `webhook_events.payload` column.

**Unsupported event types:** If `X-GitHub-Event` is not one of the supported event types (`push`, `pull_request`, `issue_comment`, `issues`), the server responds with HTTP 200 and `status: "skipped"`. A `webhook_events` row is inserted with `status: "skipped"` for audit trail purposes, but no session is loaded or created and no agent pipeline is dispatched.

**Response 200**

```json
{
  "status": "accepted",
  "delivery_id": "abc-123",
  "id": "uuid"
}
```

| Field | Type | Description |
|---|---|---|
| status | string | Always "accepted" on successful receipt |
| delivery_id | string | Echo of `X-GitHub-Delivery` header |
| id | string | Internal event record UUID |

**Response 200 (Unsupported event type)**

```json
{
  "status": "skipped",
  "delivery_id": "abc-123",
  "id": "uuid",
  "reason": "unsupported_event_type"
}
```

Returned when `X-GitHub-Event` is not one of the supported types. The `webhook_events` row is recorded for audit, but no session or pipeline dispatch occurs.

**Response 401 (HMAC mismatch)**

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_SIGNATURE",
    "message": "HMAC signature verification failed"
  }
}
```

**Response 200 (Idempotency — duplicate delivery)**

```json
{
  "status": "skipped",
  "delivery_id": "abc-123",
  "id": "uuid",
  "reason": "duplicate_delivery"
}
```

Returned when the same `X-GitHub-Delivery` was already processed (idempotency replay). The `id` refers to the existing `webhook_events` row created during the first delivery — no new row is inserted. HTTP 200 is used rather than an error status because this is the expected outcome of GitHub's at-least-once delivery guarantee, not a problem condition.

**Error Responses**

| Status | Code | When |
|---|---|---|
| 400 | INVALID_PAYLOAD | Body is not valid JSON |
| 401 | INVALID_SIGNATURE | HMAC verification failed |
| 404 | UNKNOWN_REPOSITORY | No registration matches `owner/repo` derived from the event |
| 200 | SKIPPED | Unsupported event type or duplicate delivery (see 200 responses above) |
| 503 | SERVICE_UNAVAILABLE | Server is shutting down (graceful drain) |
| 429 | RATE_LIMITED | Too many requests (10 requests per second per IP, burst limit 20). Implemented via in-memory token bucket. Exemptions: health checks are not rate limited. |

Error responses use a uniform envelope:

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_SIGNATURE",
    "message": "HMAC signature verification failed"
  }
}
```

Consumers must tolerate unknown error codes by treating them as generic 5xx errors.

### GET /health

Returns server health status.

**Response 200**

```json
{
  "status": "healthy",
  "api_version": "v1",
  "uptime_seconds": 3600,
  "active_repositories": 5,
  "active_sessions": 12,
  "in_flight_executions": 2,
  "events_processed_total": 1423
}
```

| Field | Type | Description |
|---|---|---|
| status | string | "healthy" or "unhealthy" |
| api_version | string | API contract version (e.g., "v1") |
| uptime_seconds | integer | Seconds since process start |
| active_repositories | integer | Count of registered repos with `active=true` |
| active_sessions | integer | Count of non-expired sessions |
| in_flight_executions | integer | Currently executing agent pipelines |
| events_processed_total | integer | Lifetime count of processed webhooks |

Unknown fields may be added in future versions. Consumers must ignore them.

### Admin API Authentication

All `/admin/*` endpoints require authentication via an `Authorization` header. The server is configured with an `ADMIN_TOKEN` environment variable (minimum 32 characters, must be a high-entropy random string). The client must send:

```
Authorization: Bearer <admin-token>
```

Requests without a valid token receive HTTP 401 with code `UNAUTHORIZED`.

**Token rotation:** To rotate the admin token without disrupting active admin clients, the server also accepts `ADMIN_TOKEN_OLD` during the transition window. When `ADMIN_TOKEN_OLD` is set, both the old and new tokens are accepted for authentication. Operators can restart with both variables set, wait for all clients to be updated, then remove `ADMIN_TOKEN_OLD` on a subsequent restart. If `ADMIN_TOKEN_OLD` is not provided, only `ADMIN_TOKEN` is accepted (normal operation).

**Bootstrap fallback for first deployment:** Before the admin API is available (e.g., during initial setup), repository registration can be performed via a direct SQL insert. A documented SQL script (`db/seed_registration.sql`) is provided in the repository for this purpose. After the server starts, the admin API becomes the primary registration channel.

### POST /admin/repositories

Register a new webhook target. Requires admin authentication.

**Request**

| Field | Type | Required | Description |
|---|---|---|---|
| owner | string | Yes | GitHub owner |
| repo | string | Yes | GitHub repository name |
| secret_token | string | Yes | HMAC secret for webhook verification |
| gh_token | string | Yes | GitHub API token (PAT or installation token) |
| version | string | No | Agent version for canary (default "v1") |

The request body is JSON. Unknown fields are accepted and stored in `repositories.metadata` for forward compatibility.

**Response 201**

```json
{
  "status": "created",
  "repository": {
    "id": "uuid",
    "owner": "my-org",
    "repo": "my-repo",
    "active": true,
    "version": "v1",
    "created_at": "2026-06-28T00:00:00Z"
  }
}
```

**Error Responses**

| Status | Code | When |
|---|---|---|
| 409 | ALREADY_EXISTS | Repository is already registered |
| 400 | INVALID_INPUT | Missing required field |

### DELETE /admin/repositories/{owner}/{repo}

Deregister a webhook target.

**Response 200**

```json
{
  "status": "deleted"
}
```

**Response 404**

```json
{
  "status": "error",
  "error": {
    "code": "NOT_FOUND",
    "message": "Repository not registered"
  }
}
```

**Error Responses**

| Status | Code | When |
|---|---|---|
| 401 | UNAUTHORIZED | Missing or invalid admin token |
| 404 | NOT_FOUND | Repository not registered |

### PATCH /admin/repositories/{owner}/{repo}

Update a registered repository's configuration. Requires admin authentication.

**Request**

| Field | Type | Required | Description |
|---|---|---|---|
| secret_token | string | No | New HMAC secret for webhook verification |
| gh_token | string | No | New GitHub API token |
| active | boolean | No | Enable or disable event processing |
| version | string | No | Agent version for canary |

Unknown fields are accepted and stored in `repositories.metadata` for forward compatibility.

**Response 200**

```json
{
  "status": "updated",
  "repository": {
    "id": "uuid",
    "owner": "my-org",
    "repo": "my-repo",
    "active": true,
    "version": "v1",
    "created_at": "2026-06-28T00:00:00Z"
  }
}
```

**Error Responses**

| Status | Code | When |
|---|---|---|
| 400 | INVALID_INPUT | Field value is malformed or semantically invalid |
| 401 | UNAUTHORIZED | Missing or invalid admin token |
| 404 | NOT_FOUND | Repository not registered |

### GET /admin/repositories

List all registered repositories. Requires admin authentication.

**Response 200**

```json
{
  "repositories": [
    {
      "id": "uuid",
      "owner": "my-org",
      "repo": "my-repo",
      "active": true,
      "version": "v1",
      "created_at": "2026-06-28T00:00:00Z"
    }
  ],
  "total": 1
}
```

The `secret_token` and `gh_token` fields are never returned in list responses. Consumers must ignore unknown fields in each repository object.

**Error Responses**

| Status | Code | When |
|---|---|---|
| 401 | UNAUTHORIZED | Missing or invalid admin token |

### GET /admin/repositories/{owner}/{repo}

Retrieve a single registered repository's current configuration. Requires admin authentication. The `secret_token` and `gh_token` fields are never returned.

**Response 200**

```json
{
  "repository": {
    "id": "uuid",
    "owner": "my-org",
    "repo": "my-repo",
    "active": true,
    "version": "v1",
    "created_at": "2026-06-28T00:00:00Z"
  }
}
```

Consumers must ignore unknown fields in the repository object.

**Error Responses**

| Status | Code | When |
|---|---|---|
| 401 | UNAUTHORIZED | Missing or invalid admin token |
| 404 | NOT_FOUND | Repository not registered |

### GET /admin/repositories/{owner}/{repo}/sessions

List active sessions for a specific repository.

**Response 200**

```json
{
  "sessions": [
    {
      "id": "uuid",
      "subject_type": "issue",
      "subject_id": 42,
      "conversation_length": 5,
      "created_at": "2026-06-28T00:00:00Z",
      "updated_at": "2026-06-28T01:00:00Z"
    }
  ],
  "total": 1
}
```

Conversation content is excluded from list responses. Individual session detail may be added in a future endpoint.

**Error Responses**

| Status | Code | When |
|---|---|---|
| 401 | UNAUTHORIZED | Missing or invalid admin token |
| 404 | NOT_FOUND | Repository not registered |

### GET /admin/events

List webhook events with optional filtering by `repo_id` and `status`.

**Request Query Parameters**

| Field | Type | Required | Description |
|---|---|---|---|
| repo_id | uuid | No | Filter by repository |
| status | string | No | Filter by status (received, processing, completed, failed, skipped) |
| limit | integer | No | Max results (default 50, max 200) |
| offset | integer | No | Pagination offset (default 0) |

**Response 200**

```json
{
  "events": [
    {
      "id": "uuid",
      "repo_id": "uuid",
      "delivery_id": "abc-123",
      "event_type": "push",
      "status": "completed",
      "created_at": "2026-06-28T00:00:00Z"
    }
  ],
  "total": 1
}
```

The `payload` column is excluded from list responses to reduce response size. Consumers must ignore unknown fields in each event object.

**Error Responses**

| Status | Code | When |
|---|---|---|
| 401 | UNAUTHORIZED | Missing or invalid admin token |

## Sequences

### Webhook Event Processing (Happy Path)

```
GitHub                    Server                    SQLite               Agent Pipeline
  │                         │                         │                      │
  │  POST /webhook          │                         │                      │
  │  X-Hub-Signature-256    │                         │                      │
  │  X-GitHub-Delivery      │                         │                      │
  │  X-GitHub-Event         │                         │                      │
  │────────────────────────▶│                         │                      │
  │                         │  HMAC-SHA256 verify     │                      │
  │                         │─────────────────────────│                      │
  │                         │                         │                      │
  │                         │  Dedup check (delivery_id)                      │
  │                         │─────────────────────────│                      │
  │                         │  Insert webhook_events  │                      │
  │                         │─────────────────────────│                      │
  │                         │  Lookup repository      │                      │
  │                         │─────────────────────────│                      │
  │                         │  Load or create session │                      │
  │                         │─────────────────────────│                      │
  │  200 {"status":"accepted"}                        │                      │
  │◀────────────────────────│                         │                      │
  │                         │                         │                      │
  │                         │  dispatch to thread pool│                      │
  │                         │────────────────────────────────────────────────▶
  │                         │                         │                      │
  │                         │                         │  engine.match_event()│
  │                         │                         │──────────────────────│
  │                         │                         │                      │
  │                         │                         │  session.append()    │
  │                         │                         │──────────────────────│
  │                         │                         │                      │
  │                         │                         │  run_rule.execute()  │
  │                         │                         │  (pre → agent →      │
  │                         │                         │   post → outcome)    │
  │                         │                         │──────────────────────│
  │                         │                         │                      │
  │                         │                         │  Update session      │
  │                         │  session.save()         │                      │
  │                         │◀────────────────────────│                      │
  │                         │                         │                      │
  │                         │  Update webhook_events  │                      │
  │                         │  (status=completed)     │                      │
  │                         │─────────────────────────│                      │
```

### Graceful Shutdown

```
Admin/Scheduler          Uvicorn                  In-flight Tasks         New Requests
  │                         │                         │                      │
  │  SIGTERM                │                         │                      │
  │────────────────────────▶│                         │                      │
  │                         │  Set shutdown_event     │                      │
  │                         │  Mark health=unhealthy  │                      │
  │                         │─────────────────────────│                      │
  │                         │                         │                      │
  │                         │  Reject new requests    │                      │
  │                         │    503                  │                      │
  │                         │                         │         POST /webhook│
  │                         │◀────────────────────────────────────────────────│
  │                         │    503 Service Unavailable                     │
  │                         │────────────────────────────────────────────────▶│
  │                         │                         │                      │
  │                         │  Wait for in-flight     │                      │
  │                         │  tasks (max 30s)        │                      │
  │                         │────────────────────────▶│                      │
  │                         │                         │  Complete pipeline   │
  │                         │────────────────────────▶│                      │
  │                         │  Cancel remaining       │                      │
  │                         │  (if drain timeout)     │                      │
  │                         │────────────────────────▶│                      │
  │                         │  Exit process           │                      │
```

### Retry on GitHub API Failure

```
Pipeline Bridge          run_steps._gh_with_retry     gh CLI              GitHub API
  │                         │                         │                      │
  │  apply_labels()         │                         │                      │
  │────────────────────────▶│                         │                      │
  │                         │  gh issue edit ...      │                      │
  │                         │────────────────────────▶│                      │
  │                         │                         │  POST /repos/...    │
  │                         │                         │─────────────────────▶│
  │                         │                         │  429 / 5xx          │
  │                         │                         │◀─────────────────────│
  │                         │  CalledProcessError     │                      │
  │                         │  Retry 1 (wait 1s)      │                      │
  │                         │────────────────────────▶│                      │
  │                         │                         │  POST /repos/...    │
  │                         │                         │─────────────────────▶│
  │                         │                         │  Timeout            │
  │                         │  Retry 2 (wait 2s)      │                      │
  │                         │────────────────────────▶│                      │
  │                         │                         │  POST /repos/...    │
  │                         │                         │─────────────────────▶│
  │                         │                         │  200                │
  │                         │                         │◀─────────────────────│
  │                         │  Success                │                      │
  │  labels applied         │                         │                      │
  │◀────────────────────────│                         │                      │
```

## Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Web framework | FastAPI + Uvicorn | Async-native, built-in OpenAPI docs, BackgroundTasks for non-blocking dispatch, lifespan events for graceful shutdown. Recommended by existing-solutions survey. |
| Session persistence | SQLite (aiosqlite + WAL mode) | Zero-dependency, single-file, Docker-volume-mountable. Meets NFR-07 (single container). WAL mode allows concurrent reads during writes. Migration path to PostgreSQL if load grows. |
| HMAC verification | stdlib `hmac.compare_digest` | Canonical GitHub reference implementation. No external dependency. Timing-safe comparison. |
| Pipeline dispatch | `run_in_executor` (thread pool) | The existing engine is synchronous. Wrapping via thread pool avoids rewriting the pipeline in async. Bounded thread pool prevents resource exhaustion; default max 20 workers, configurable via `THREAD_POOL_MAX_WORKERS` environment variable. If `run_in_executor` submission fails because the pool queue is full, the exception is caught and logged, the `webhook_events` row is updated to `status=failed`, and the HTTP response (already sent as 200) is supplemented by the logged error. This is an at-most-once delivery: the event is received and acknowledged but execution is deferred or failed. |
| Env var isolation | Parameter injection with env var fallback | Server passes all context as function parameters to pipeline code. CLI path continues using env vars. Eliminates race condition under concurrent multi-repo execution without changing CLI behavior. |
| Retry strategy | 3 attempts (initial + 2 retries), exponential backoff (delays 1s, 2s), `CalledProcessError` and API-level transient indicators | Matches NFR-06. Retries on `subprocess.CalledProcessError` (non-zero exit) and on zero-exit cases where stderr or stdout indicates an API-level retryable condition (e.g., HTTP 429/5xx in `gh` response output, rate-limit headers). The 4s backoff from the exponential pattern is never reached because max 3 attempts are made. Immediate re-raise on other exceptions (e.g., `FileNotFoundError`). Failure logged at ERROR; pipeline continues to next step. |
| Webhook idempotency | Dedup via `X-GitHub-Delivery` unique constraint | SQLite unique constraint on `delivery_id`. Duplicates get HTTP 200 with `reason: duplicate_delivery`. At-most-once agent execution per delivery. |
| Graceful shutdown | Uvicorn lifespan handler + `asyncio.Event` + task tracking | Set shutdown flag, reject new requests with 503, drain in-flight tasks (max 30s), cancel stragglers, exit. |
| Structured logging | `structlog` with JSON output | Server emits structured events for webhook receipt, HMAC result, rule matches, agent execution, gh calls, retries, and errors. CLI path unchanged (plain-text). |
| Rate limiting | In-memory token bucket (10 req/s per IP, burst 20) | Protects against webhook storms and accidental misconfiguration. Token bucket is per-IP and resets on server restart. Health checks are exempt. Rate-limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) are returned in all 429 responses. The `X-RateLimit-Reset` value is an absolute Unix timestamp computed relative to the current token bucket refill window — after a restart, the timestamp represents the new window and consumers must not carry over a pre-restart `X-RateLimit-Reset` value. Rate-limit thresholds are configurable via `RATE_LIMIT_REQUESTS_PER_SEC` (default 10) and `RATE_LIMIT_BURST` (default 20) environment variables. |
| Skill file distribution | Clone agent repository at container startup | The `AGENTS_REPOSITORY` is cloned during the startup lifecycle phase, before the health endpoint reports healthy and before any webhooks are accepted. This ensures consistent latency: the first webhook never bears a cold-start clone. Cloning blocks readiness, which is acceptable because startup is a rare event. The clone path can be overridden via a Docker volume mount for production deployments that pre-distribute skills. |
| API versioning | URL prefix-based (`/v1/webhook`, `/v1/admin/repositories`). Additive-only within a major version. Breaking changes require a new major version with a documented deprecation window. | All endpoints are versioned via URL prefix. Future major versions (e.g., `/v2/webhook`) may change behavior. The current `/webhook`, `/health`, and `/admin/*` paths are aliases for `/v1/*`. The health response exposes `api_version` (the API contract version, e.g., `"v1"`). Deprecation window: at least one minor release cycle between announcement and removal of a deprecated version. New optional fields can be added at any minor version without a deprecation period. |
| Forward compatibility | Open enums, unknown field tolerance, additive-only contract | All schemas document that consumers must ignore unknown fields. Enum values that are not recognized must be handled without error. New fields are always optional. API version is the `api_version` field in the health response and `repositories.version` for canary deployments. New enum values are additive only; no existing enum value is removed without a major version bump and a deprecation window of at least one release cycle. |

## Risks and Unknowns

1. **SQLite write contention under load**: At 10 repos with ~1 event/sec each, SQLite's single-writer may become a bottleneck. Mitigation: a per-session `threading.Lock` (keyed by `(repo_id, subject_type, subject_id)`) serializes writes within each session. The lock is acquired in the thread pool worker before any SQLite write and released after the write completes. `threading.Lock` is safe across the `run_in_executor` thread pool boundary, unlike `asyncio.Lock`. This allows concurrent writes across different sessions while preventing write interleaving within a single session's conversation history. Escalation path: migration to PostgreSQL (schema-compatible change).
2. **Thread pool exhaustion**: If all 20 thread pool workers are occupied by long-running agent executions, new webhooks queue up and risk violating NFR-03 (5s dispatch). Mitigation: monitor pool queue depth; alert at 80% utilization. The bounded pool prevents OOM but may delay dispatch.
3. **`opencode` CLI version drift**: The Docker image pins an `opencode` version. If the agent CLI evolves, the server image must be rebuilt. Mitigation: make `opencode` version a build arg in the Dockerfile.
4. **Skill file distribution**: Cloning the agent repository at startup may fail or time out, blocking the server from becoming healthy. Mitigation: retry with backoff; fall back to a cached clone if available (from a prior startup); document that a volume mount is the production-reliable approach.
5. **Behavioral identity verification**: The refactored pipeline must produce identical outcomes for the same input as the CLI path. Mitigation: run the acceptance criteria suite against both paths in CI before deploying the server.
6. **GitHub API rate limits**: All outbound GitHub API calls share the per-repository token. Rate limit exhaustion blocks agent outcomes. Mitigation: retry with backoff (NFR-06); log rate-limit headers for monitoring.
7. **No TLS termination in the server**: The server listens on HTTP only. TLS termination is expected to be handled by a reverse proxy (nginx, Caddy, or a cloud load balancer) deployed in front of the container. **Deployment guidance**: the reverse proxy must support HTTP/1.1 (for GitHub webhook delivery) and should be configured with a TLS certificate from Let's Encrypt or a commercial CA. Health checks from the load balancer should target `GET /health` on the HTTP port. The server exposes `PORT` (default 8080) as the listen address.
8. **Session table unbounded growth**: Without a reaper, the `sessions` table grows indefinitely. Mitigation: background reaper deletes sessions older than `SESSION_TTL_HOURS` (default 168, i.e., 7 days). The reaper runs every hour and logs its deletion count.
9. **Webhook events table unbounded growth**: Without a retention policy, the `webhook_events` table grows indefinitely. Mitigation: daily cleanup task deletes rows older than `EVENTS_RETENTION_DAYS` (default 90). Both retention and reaper tasks use SQL with LIMIT to avoid long-running transactions.
10. **Admin token rotation disruption**: Restarting with a new `ADMIN_TOKEN` invalidates all existing admin sessions at once. Mitigation: support `ADMIN_TOKEN_OLD` for a transition window, giving operators time to update clients.

## Out of Scope

- **GitHub App lifecycle management**: Automatic registration/deregistration on GitHub App install/uninstall events is not specified. Initial implementation requires manual registration via the admin API. A SQL seed script (`db/seed_registration.sql`) is provided for first-deployment bootstrap before the admin API key is configured.
- **Webhook delivery retry**: The server does not retry webhook deliveries from GitHub. GitHub retries at-least-once delivery on its own schedule. The server's idempotency handling ensures duplicate deliveries are safe.
- **Multi-host deployment**: The specification targets a single Docker container. Horizontal scaling, load balancing, and shared SQLite across hosts are not covered.
- **Admin dashboard UI**: FR-09 specifies a REST API only. No web UI is specified.
- **Metrics export**: No Prometheus, OpenTelemetry, or statsd export is specified. Structured logs are the observability channel.
- **Webhook secret rotation**: The initial specification does not include a dedicated rotation endpoint. Operators update the `secret_token` field via `PATCH /admin/repositories/{owner}/{repo}` (which accepts an optional `secret_token` field to replace the existing value) or by direct SQLite update. A future version may add a rotation schedule and expiry tracking.
- **Database migrations**: The initial schema is created at server startup via `CREATE TABLE IF NOT EXISTS`. No migration framework is specified. The `db/` directory will contain numbered migration SQL files (e.g., `001_initial.sql`, `002_add_session_expiry.sql`) that are applied in order on startup. Schema rollback is manual (restore from backup or apply a reverse migration file). This convention is established from day one even though initial migrations are trivial, ensuring a migration path exists before schema changes accumulate.
