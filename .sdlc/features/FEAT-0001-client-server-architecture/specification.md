---
issue: "#16"
title: "Client/Server architecture"
status: in-review
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

The `webhook_events` table serves as an idempotency log and audit trail. The `delivery_id` unique constraint prevents duplicate processing when GitHub retries delivery. `status` is an open enum — consumers must handle unknown values gracefully by treating them as informational without breaking.

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
  "status": "rejected",
  "reason": "invalid_signature"
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

Returned when the same `X-GitHub-Delivery` was already processed. This is not an error — it is the expected outcome of GitHub's at-least-once delivery guarantee.

**Error Responses**

| Status | Code | When |
|---|---|---|
| 400 | INVALID_PAYLOAD | Body is not valid JSON |
| 401 | INVALID_SIGNATURE | HMAC verification failed |
| 404 | UNKNOWN_REPOSITORY | No registration matches `owner/repo` derived from the event |
| 503 | SERVICE_UNAVAILABLE | Server is shutting down (graceful drain) |
| 429 | RATE_LIMITED | Too many requests (optional, if rate limiting is added later) |

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
  "version": "1.0.0",
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
| version | string | Server software version |
| uptime_seconds | integer | Seconds since process start |
| active_repositories | integer | Count of registered repos with `active=true` |
| active_sessions | integer | Count of non-expired sessions |
| in_flight_executions | integer | Currently executing agent pipelines |
| events_processed_total | integer | Lifetime count of processed webhooks |

Unknown fields may be added in future versions. Consumers must ignore them.

### POST /admin/repositories (optional, FR-09)

Register a new webhook target.

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
| Pipeline dispatch | `run_in_executor` (thread pool) | The existing engine is synchronous. Wrapping via thread pool avoids rewriting the pipeline in async. Bounded thread pool (max 20 workers) prevents resource exhaustion. |
| Env var isolation | Parameter injection with env var fallback | Server passes all context as function parameters to pipeline code. CLI path continues using env vars. Eliminates race condition under concurrent multi-repo execution without changing CLI behavior. |
| Retry strategy | 3 attempts, exponential backoff (1s/2s/4s), `CalledProcessError` only | Matches NFR-06. Only retries on non-zero subprocess exit (transient errors). Immediate re-raise on other exceptions. Failure logged at ERROR; pipeline continues to next step. |
| Webhook idempotency | Dedup via `X-GitHub-Delivery` unique constraint | SQLite unique constraint on `delivery_id`. Duplicates get HTTP 409 with `reason: duplicate_delivery`. At-most-once agent execution per delivery. |
| Graceful shutdown | Uvicorn lifespan handler + `asyncio.Event` + task tracking | Set shutdown flag, reject new requests with 503, drain in-flight tasks (max 30s), cancel stragglers, exit. |
| Structured logging | `structlog` with JSON output | Server emits structured events for webhook receipt, HMAC result, rule matches, agent execution, gh calls, retries, and errors. CLI path unchanged (plain-text). |
| Skill file distribution | Clone agent repository at container startup | Simplest approach. The `AGENTS_REPOSITORY` is cloned on first webhook event or at startup. Cold-start latency is acceptable vs. rebuild on every skill change. Can be overridden via Docker volume mount. |
| Forward compatibility | Open enums, unknown field tolerance, additive-only contract | All schemas document that consumers must ignore unknown fields. Enum values that are not recognized must be handled without error. New fields are always optional. API version is the `version` field in health response and `repositories.version` for canary. |

## Risks and Unknowns

1. **SQLite write contention under load**: At 10 repos with ~1 event/sec each, SQLite's single-writer may become a bottleneck. Mitigation: per-repo `asyncio.Lock` serializes writes per session. Escalation path: migration to PostgreSQL (schema-compatible change).
2. **Thread pool exhaustion**: If all 20 thread pool workers are occupied by long-running agent executions, new webhooks queue up and risk violating NFR-03 (5s dispatch). Mitigation: monitor pool queue depth; alert at 80% utilization. The bounded pool prevents OOM but may delay dispatch.
3. **`opencode` CLI version drift**: The Docker image pins an `opencode` version. If the agent CLI evolves, the server image must be rebuilt. Mitigation: make `opencode` version a build arg in the Dockerfile.
4. **Skill file distribution**: Cloning the agent repository at startup may fail or time out. Mitigation: retry with backoff; fall back to a cached clone if available; document that a volume mount is the production-reliable approach.
5. **Behavioral identity verification**: The refactored pipeline must produce identical outcomes for the same input as the CLI path. Mitigation: run the acceptance criteria suite against both paths in CI before deploying the server.
6. **GitHub API rate limits**: All outbound GitHub API calls share the per-repository token. Rate limit exhaustion blocks agent outcomes. Mitigation: retry with backoff (NFR-06); log rate-limit headers for monitoring.
7. **No TLS termination in the server**: The specification does not mandate TLS in the container. In production, a reverse proxy (nginx, Caddy) or load balancer terminates TLS. The server listens on HTTP only.

## Out of Scope

- **GitHub App lifecycle management**: Automatic registration/deregistration on GitHub App install/uninstall events is not specified. Initial implementation requires manual registration via the admin API or direct SQLite insert.
- **Webhook delivery retry**: The server does not retry webhook deliveries from GitHub. GitHub retries at-least-once delivery on its own schedule. The server's idempotency handling ensures duplicate deliveries are safe.
- **Multi-host deployment**: The specification targets a single Docker container. Horizontal scaling, load balancing, and shared SQLite across hosts are not covered.
- **Admin dashboard UI**: FR-09 specifies a REST API only. No web UI is specified.
- **Metrics export**: No Prometheus, OpenTelemetry, or statsd export is specified. Structured logs are the observability channel.
- **Webhook secret rotation**: No endpoint or mechanism for rotating `secret_token` is specified. Operators update the `repositories` table directly.
- **Database migrations**: The initial schema is created at server startup via `CREATE TABLE IF NOT EXISTS`. No migration framework is specified. Schema changes are applied manually or via a migration script.
