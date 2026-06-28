---
issue: "#16"
title: "Client/Server architecture"
status: in-review
revision: 2
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
│  │              │     └──────────────────┘              │            │
│  └──────────────┘                                       │            │
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

**Key rotation procedure:** To rotate the encryption key, the operator provides both `TOKEN_ENCRYPTION_KEY_OLD` (the current key) and `TOKEN_ENCRYPTION_KEY` (the new key) as environment variables at startup. The server reads every token from the database, decrypts with `TOKEN_ENCRYPTION_KEY_OLD`, re-encrypts with `TOKEN_ENCRYPTION_KEY`, and writes the updated ciphertext. After a successful rotation, `TOKEN_ENCRYPTION_KEY_OLD` is unset and only `TOKEN_ENCRYPTION_KEY` is retained. If `TOKEN_ENCRYPTION_KEY_OLD` is not provided, a normal startup proceeds (existing tokens are decrypted with `TOKEN_ENCRYPTION_KEY`).

**Migration from plaintext to encryption (and back):** When `TOKEN_ENCRYPTION_KEY` is first set after a period of running without it, the server re-encrypts all plaintext tokens on startup. To decrypt (returning to development mode), set `TOKEN_ENCRYPTION_KEY` to the current key and `TOKEN_ENCRYPTION_KEY_OLD` to empty — the server decrypts all tokens to plaintext and logs a warning. This path exists only for development and disaster recovery; production deployments should always set `TOKEN_ENCRYPTION_KEY`.

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

Sessions are keyed by `(repo_id, subject_type, subject_id)`. The `conversation_history` field stores the agent's conversation as a JSON array; each entry has `role` (user/assistant/system), `content`, and `timestamp`. The `context` field stores pipeline state. Consumers must preserve unknown fields in both JSON columns across read-write cycles (read-modify-write must retain unrecognized keys).

**Session expiry and cleanup:** Sessions expire after 7 days of inactivity (no new webhook events for that `(repo_id, subject_type, subject_id)` key). Expiry is checked lazily: when a new webhook event arrives for an expired session, the server creates a fresh session instead of loading the stale one. A background reaper task runs every hour, deleting sessions whose `updated_at` is older than a configurable `SESSION_TTL_HOURS` (default 168, i.e., 7 days). The reaper logs its deletion count and skips if database contention is detected (SQLITE_BUSY). Session count is tracked in the `/health` endpoint as active (non-expired) sessions. The `SESSIONS_MAX_AGE_HOURS` environment variable overrides the default TTL.

The `repositories.version` field supports canary deployments (FR-10) by selecting runtime configuration variants within a single container. The server maintains a mapping from version strings (e.g., `"v1"`, `"v2-canary"`) to agent configuration bundles: model identifier, system prompt template path, skill repository reference, and maximum iteration count. When processing a webhook for a repository with `version: "v2-canary"`, the server selects the `v2-canary` config bundle. All versions share the same engine code and binary; only the configuration differs. The set of available versions is defined in a YAML file mounted into the container (`/etc/llmaw/versions.yaml`), and the default version (`"v1"`) is always present. This approach satisfies multi-version support within NFR-07's single-container constraint. Future growth to separate binaries would require breaking NFR-07 or switching to a sidecar model.

### `webhook_events`

| Field | Type | Constraints | Description |
|---|---|---|---|
| id | uuid | PK, not null | Internal identifier |
| repo_id | uuid | FK → repositories.id, not null | Target repository |
| delivery_id | text | not null, unique | `X-GitHub-Delivery` header value |
| event_type | text | not null | e.g., "push", "pull_request", "issues" |
| payload | json | not null | Full webhook payload |
| hmac_valid | boolean | not null | Whether HMAC signature was verified |
| status | text | not null | "received", "processing", "completed", "failed", "skipped" (dedup) |
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

**Response 200**

```json
{
  "status": "accepted",
  "delivery_id": "abc-123",
  "event_id": "uuid"
}
```

| Field | Type | Description |
|---|---|---|
| status | string | Always "accepted" on successful receipt |
| delivery_id | string | Echo of `X-GitHub-Delivery` header |
| event_id | string | Internal event record UUID |

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

**Response 409 (Idempotency)**

```json
{
  "status": "skipped",
  "delivery_id": "abc-123",
  "event_id": "uuid",
  "reason": "duplicate_delivery"
}
```

Returned when the same `X-GitHub-Delivery` was already processed. The `event_id` refers to the existing `webhook_events` row created during the first delivery — no new row is inserted. This is not an error; it is the expected outcome of GitHub's at-least-once delivery guarantee.

**Error Responses**

| Status | Code | When |
|---|---|---|
| 400 | INVALID_PAYLOAD | Body is not valid JSON |
| 401 | INVALID_SIGNATURE | HMAC verification failed |
| 404 | UNKNOWN_REPOSITORY | No registration matches `owner/repo` derived from the event |
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

All `/admin/*` endpoints require authentication via an `Authorization` header. The server is configured with an `ADMIN_TOKEN` environment variable. The client must send:

```
Authorization: Bearer <admin-token>
```

Requests without a valid token receive HTTP 401 with code `UNAUTHORIZED`.

**Token rotation:** To rotate the admin token without disrupting active admin clients, the server also accepts `ADMIN_TOKEN_OLD` during the transition window. When `ADMIN_TOKEN_OLD` is set, both the old and new tokens are accepted for authentication. Operators can restart with both variables set, wait for all clients to be updated, then remove `ADMIN_TOKEN_OLD` on a subsequent restart. If `ADMIN_TOKEN_OLD` is not provided, only `ADMIN_TOKEN` is accepted (normal operation).

### POST /admin/repositories (optional, FR-09)

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
    "active": true
  }
}
```

**Error Responses**

| Status | Code | When |
|---|---|---|
| 409 | ALREADY_EXISTS | Repository is already registered |
| 400 | INVALID_INPUT | Missing required field |

### DELETE /admin/repositories/{owner}/{repo} (optional, FR-09)

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

### PATCH /admin/repositories/{owner}/{repo} (optional, FR-09)

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
    "active": true
  }
}
```

**Error Responses**

| Status | Code | When |
|---|---|---|
| 401 | UNAUTHORIZED | Missing or invalid admin token |
| 404 | NOT_FOUND | Repository not registered |

### GET /admin/repositories (optional, FR-09)

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

### GET /admin/repositories/{owner}/{repo}/sessions (optional, FR-09)

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

### GET /admin/events (optional, FR-09)

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
| Pipeline dispatch | `run_in_executor` (thread pool) | The existing engine is synchronous. Wrapping via thread pool avoids rewriting the pipeline in async. Bounded thread pool (max 20 workers) prevents resource exhaustion. If `run_in_executor` submission fails because the pool queue is full, the exception is caught and logged, the `webhook_events` row is updated to `status=failed`, and the HTTP response (already sent as 200) is supplemented by the logged error. This is an at-most-once delivery: the event is received and acknowledged but execution is deferred or failed. |
| Env var isolation | Parameter injection with env var fallback | Server passes all context as function parameters to pipeline code. CLI path continues using env vars. Eliminates race condition under concurrent multi-repo execution without changing CLI behavior. |
| Retry strategy | 3 attempts (initial + 2 retries), exponential backoff (delays 1s, 2s), `CalledProcessError` and API-level transient indicators | Matches NFR-06. Retries on `subprocess.CalledProcessError` (non-zero exit) and on zero-exit cases where stderr or stdout indicates an API-level retryable condition (e.g., HTTP 429/5xx in `gh` response output, rate-limit headers). The 4s backoff from the exponential pattern is never reached because max 3 attempts are made. Immediate re-raise on other exceptions (e.g., `FileNotFoundError`). Failure logged at ERROR; pipeline continues to next step. |
| Webhook idempotency | Dedup via `X-GitHub-Delivery` unique constraint | SQLite unique constraint on `delivery_id`. Duplicates get HTTP 409 with `reason: duplicate_delivery`. At-most-once agent execution per delivery. |
| Graceful shutdown | Uvicorn lifespan handler + `asyncio.Event` + task tracking | Set shutdown flag, reject new requests with 503, drain in-flight tasks (max 30s), cancel stragglers, exit. |
| Structured logging | `structlog` with JSON output | Server emits structured events for webhook receipt, HMAC result, rule matches, agent execution, gh calls, retries, and errors. CLI path unchanged (plain-text). |
| Rate limiting | In-memory token bucket (10 req/s per IP, burst 20) | Protects against webhook storms and accidental misconfiguration. Token bucket is per-IP and resets on server restart. Health checks are exempt. Rate-limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) are returned in all 429 responses. The `X-RateLimit-Reset` value is an absolute Unix timestamp computed relative to the current token bucket refill window — after a restart, the timestamp represents the new window and consumers must not carry over a pre-restart `X-RateLimit-Reset` value. Rate-limit thresholds are configurable via `RATE_LIMIT_REQUESTS_PER_SEC` (default 10) and `RATE_LIMIT_BURST` (default 20) environment variables. |
| Skill file distribution | Clone agent repository at container startup | The `AGENTS_REPOSITORY` is cloned during the startup lifecycle phase, before the health endpoint reports healthy and before any webhooks are accepted. This ensures consistent latency: the first webhook never bears a cold-start clone. Cloning blocks readiness, which is acceptable because startup is a rare event. The clone path can be overridden via a Docker volume mount for production deployments that pre-distribute skills. |
| API versioning | URL prefix-based (`/v1/webhook`, `/v1/admin/repositories`). Additive-only within a major version. Breaking changes require a new major version with a documented deprecation window. | All endpoints are versioned via URL prefix. Future major versions (e.g., `/v2/webhook`) may change behavior. The current `/webhook`, `/health`, and `/admin/*` paths are aliases for `/v1/*`. The health response exposes `api_version` (the API contract version, e.g., `"v1"`). Deprecation window: at least one minor release cycle between announcement and removal of a deprecated version. New optional fields can be added at any minor version without a deprecation period. |
| Forward compatibility | Open enums, unknown field tolerance, additive-only contract | All schemas document that consumers must ignore unknown fields. Enum values that are not recognized must be handled without error. New fields are always optional. API version is the `api_version` field in the health response and `repositories.version` for canary deployments. New enum values are additive only; no existing enum value is removed without a major version bump and a deprecation window of at least one release cycle. |

## Risks and Unknowns

1. **SQLite write contention under load**: At 10 repos with ~1 event/sec each, SQLite's single-writer may become a bottleneck. Mitigation: a per-session `asyncio.Lock` serializes writes within each session (keyed by `(repo_id, subject_type, subject_id)`). This allows concurrent writes across different sessions while preventing write interleaving within a single session's conversation history. Escalation path: migration to PostgreSQL (schema-compatible change).
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

- **GitHub App lifecycle management**: Automatic registration/deregistration on GitHub App install/uninstall events is not specified. Initial implementation requires manual registration via the admin API or direct SQLite insert.
- **Webhook delivery retry**: The server does not retry webhook deliveries from GitHub. GitHub retries at-least-once delivery on its own schedule. The server's idempotency handling ensures duplicate deliveries are safe.
- **Multi-host deployment**: The specification targets a single Docker container. Horizontal scaling, load balancing, and shared SQLite across hosts are not covered.
- **Admin dashboard UI**: FR-09 specifies a REST API only. No web UI is specified.
- **Metrics export**: No Prometheus, OpenTelemetry, or statsd export is specified. Structured logs are the observability channel.
- **Webhook secret rotation**: The initial specification does not include a dedicated rotation endpoint. Operators update the `secret_token` field via `PATCH /admin/repositories/{owner}/{repo}` (which accepts an optional `secret_token` field to replace the existing value) or by direct SQLite update. A future version may add a rotation schedule and expiry tracking.
- **Database migrations**: The initial schema is created at server startup via `CREATE TABLE IF NOT EXISTS`. No migration framework is specified. The `db/` directory will contain numbered migration SQL files (e.g., `001_initial.sql`, `002_add_session_expiry.sql`) that are applied in order on startup. Schema rollback is manual (restore from backup or apply a reverse migration file). This convention is established from day one even though initial migrations are trivial, ensuring a migration path exists before schema changes accumulate.
