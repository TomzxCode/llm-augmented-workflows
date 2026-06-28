---
issue: "#16"
title: "Client/Server architecture"
status: draft
---

# Implementation Plan: Client/Server architecture

## Goal

Replace GitHub Actions as the execution substrate with a hosted HTTP server (FastAPI + Uvicorn in a single Docker container) that receives GitHub webhook events, verifies HMAC payload signatures, dispatches events through the existing agent pipeline (refactored for parameter-based context), and persists session state to SQLite. Deliver the server as a deployable container with admin API, telemetry instrumentation, and operational runbooks.

## Phases

### Phase 1: Engine Refactoring — Parameter Injection

**Goal:** The existing pipeline (`engine.py`, `run_rule`, `run_steps`, `apply_outcome`) accepts all context as function parameters instead of environment variables, eliminating race conditions under concurrent execution. The CLI path continues to work unchanged by providing the same values from env vars.

**Effort:** 5 person-days
**Depends on:** None

**Deliverables:**
- [ ] Refactor `engine.py` entry points to accept context (repo config, event payload, session history) as explicit function parameters
- [ ] Create adapter layer in CLI path that reads env vars and passes them as parameters
- [ ] Create adapter layer for server path that receives context from the pipeline bridge
- [ ] Run existing test suite against both the CLI path (env var) and parameter path to verify behavioral identity
- [ ] Implement `_gh_with_retry` with exponential backoff (3 attempts, 1s/2s delays) — shared by both deployment paths

### Phase 2: Server Foundation — Scaffolding, Schema, Lifecycle

**Goal:** The server binary boots, applies schema migrations, loads version configuration, clones the skills repository, exposes a health check, and handles graceful shutdown. The database schema (all tables + indexes) is created.

**Effort:** 5 person-days
**Depends on:** Phase 1

**Deliverables:**
- [ ] FastAPI + Uvicorn application scaffold with lifespan handler
- [ ] SQLite schema creation at startup (all tables, indexes, foreign keys with ON DELETE CASCADE)
- [ ] Schema migration runner (`db/001_initial.sql`, `db/002_...`) — applied in order on startup
- [ ] Version configuration loader (`/etc/llmaw/versions.yaml`) with fallback to `v1` on missing key
- [ ] Skills repository clone at startup (`AGENTS_REPOSITORY`) with retry and cached fallback
- [ ] Token re-encryption startup phase (AES-256-GCM + HKDF) with progress logging and timeout
- [ ] `GET /health` endpoint returning status, api_version, uptime, active_repos, active_sessions, in_flight, events_processed_total
- [ ] Graceful shutdown (SIGTERM → set shutdown flag, mark unhealthy, drain in-flight tasks max 30s, cancel stragglers, exit)
- [ ] Dockerfile with pinned `opencode` version as build arg
- [ ] Thread pool configuration (`THREAD_POOL_MAX_WORKERS`, default 20)

### Phase 3: Webhook Ingestion Pipeline

**Goal:** The server accepts POST /webhook, verifies HMAC, deduplicates by delivery ID, resolves the repository, loads (or creates) the session, dispatches the pipeline, and responds to GitHub.

**Effort:** 6 person-days
**Depends on:** Phase 2

**Deliverables:**
- [ ] HMAC-SHA256 verification middleware (stdlib `hmac.compare_digest`)
- [ ] Webhook payload logging (raw body captured before parsing)
- [ ] Delivery dedup via `delivery_id` unique constraint with idempotent 200 response
- [ ] Repository resolution from event payload `(owner, repo)`
- [ ] Supported event type filtering (`push`, `pull_request`, `issue_comment`, `issues`); others get 200 `skipped`
- [ ] Session store: load existing session or create new; TTL check at load time (default 168h)
- [ ] Per-session `threading.Lock` for write serialization keyed by `(repo_id, subject_type, subject_id)`
- [ ] Pipeline bridge: dispatch to thread pool via `run_in_executor`; update `webhook_events.status` on completion
- [ ] Rate limiting middleware: in-memory token bucket (10 req/s per IP, burst 20, exempt health checks, configurable)
- [ ] Error response uniform envelope for all error conditions
- [ ] API versioning: dual-route registration (`/webhook` and `/v1/webhook`)

### Phase 4: Admin API

**Goal:** Operators can register, list, view, update, and deregister repositories; list events and sessions. All endpoints require admin token authentication with rotation support.

**Effort:** 4 person-days
**Depends on:** Phase 2

**Deliverables:**
- [ ] `ADMIN_TOKEN` / `ADMIN_TOKEN_OLD` authentication middleware (Bearer token, minimum 32 chars)
- [ ] `POST /admin/repositories` — register repository (accepts metadata, auth_type, gh_token_expires_at; stores unknown fields in metadata)
- [ ] `GET /admin/repositories` — list all repositories (never exposes gh_token or secret_token)
- [ ] `GET /admin/repositories/{owner}/{repo}` — get single repository
- [ ] `PATCH /admin/repositories/{owner}/{repo}` — update repository fields (accepts unknown fields → metadata)
- [ ] `DELETE /admin/repositories/{owner}/{repo}` — deregister (cascade deletes sessions and events)
- [ ] `GET /admin/repositories/{owner}/{repo}/sessions` — list sessions for a repo
- [ ] `GET /admin/events` — list events with filtering by repo_id, status, pagination
- [ ] SQL bootstrap seed script (`db/seed_registration.sql`) for first deployment
- [ ] Admin token rotation support with `ADMIN_TOKEN_OLD` transition window

### Phase 5: Token & Background Task Management

**Goal:** GitHub tokens are encrypted at rest, refreshed before expiry (for installation tokens), and the database remains free of stale sessions and old events.

**Effort:** 4 person-days
**Depends on:** Phase 2

**Deliverables:**
- [ ] Token encryption layer: AES-256-GCM + HKDF `TOKEN_ENCRYPTION_KEY` — transparent encrypt-on-write, decrypt-on-read
- [ ] Token re-encryption startup with batch progress logging, per-row error tolerance, configurable timeout, and `llmaw-admin reencrypt-tokens` maintenance command
- [ ] Migration from plaintext to encryption support
- [ ] Background token refresh task (every 5 min, refresh tokens expiring within 10 min, for `installation` and `user_token` auth types)
- [ ] Consecutive failure tracking (3 failures → disable repository, set `active=false`)
- [ ] PAT expiry warning logging (`PAT_EXPIRY_WARNING_DAYS`)
- [ ] Background session reaper (hourly, deletes sessions older than TTL, logs count, skips on SQLITE_BUSY)
- [ ] Background event retention cleanup (daily at midnight, deletes events older than `EVENTS_RETENTION_DAYS`, limit-batched)
- [ ] `llmaw-admin decrypt-tokens` offline tool for development/disaster recovery

### Phase 6: Observability & Telemetry Instrumentation

**Goal:** All components emit structured logs, counters, histograms, and traces. Operators can monitor webhook throughput, pipeline health, token refresh, and session lifecycle. Alerts fire on SLO violations.

**Effort:** 4 person-days
**Depends on:** Phase 3

**Deliverables:**
- [ ] Structured logging middleware emitting `structlog` JSON events for every middleware and route handler
- [ ] All telemetry events from telemetry.md implemented as structlog log calls (webhook_received, hmac_verification, dedup, pipeline lifecycle, session lifecycle, token refresh, admin API, rate limit, shutdown, re-encryption, reaper, cleanup)
- [ ] Counter metrics: webhook requests by outcome, pipeline completions/failures, token refresh completions/failures, admin API requests, HMAC failures, rate limit exceeded, graceful shutdown cancellations, repositories disabled, reaper deletions
- [ ] Histogram metrics: webhook request duration, pipeline dispatch duration, pipeline execution duration
- [ ] Gauge metrics: active sessions, active repositories, in-flight executions, thread pool queue depth, SQLite WAL file size, GitHub API rate limit remaining, token refresh failure streak per repo
- [ ] SQLite write contention counter (SQLITE_BUSY retries by operation)
- [ ] OpenTelemetry tracing spans across webhook processing path (post_webhook → verify_hmac → check_dedup → lookup_repository → load_or_create_session → dispatch_pipeline → execute_pipeline)
- [ ] Prometheus `/metrics` endpoint via prometheus-fastapi-instrumentator
- [ ] Server Operations Dashboard definition (Grafana JSON model): throughput, latency, error rates, active sessions, token refresh, rate limiting panels
- [ ] Alert rules (PromQL): critical (pipeline failure >5%, repository auto-disabled), warning (webhook errors >1%, HMAC failures >1%, token refresh spiking, thread pool saturated), info (shutdown cancellations, reaper large cleanup)
- [ ] SLO tracking documentation and runbook references

### Phase 7: Testing & Hardening

**Goal:** The server is tested for correctness, performance, and reliability under load. Behavioral identity with the CLI path is verified.

**Effort:** 5 person-days
**Depends on:** Phase 3, Phase 4, Phase 5

**Deliverables:**
- [ ] Unit tests for HMAC verification, dedup, rate limiting, token encryption/decryption, session TTL
- [ ] Integration tests: webhook → pipeline dispatch → session persistence → status update
- [ ] Admin API CRUD tests with auth
- [ ] Behavioral identity test suite: same input produces same agent outcome via CLI path and server path
- [ ] Load test: 10 repositories, 10 events/sec aggregate, verify p99 dispatch latency <5s
- [ ] Graceful shutdown test: in-flight tasks drain within 30s timeout, no dropped webhooks
- [ ] Token refresh failure cascade test: 3 consecutive failures → repository disabled
- [ ] Schema migration test: migration files apply in order; rollback by restore
- [ ] Docker container build and smoke test

## Milestones

| Milestone | Phase | Success Criteria |
|---|---|---|
| M1: Engine refactored | Phase 1 | Existing test suite passes under both CLI env-var path and parameterized path; identical output for same input |
| M2: Server boots healthy | Phase 2 | Docker container starts, `/health` returns 200 with all fields populated, schema migrations applied, versions.yaml loaded, skills repo cloned |
| M3: Webhook processed end-to-end | Phase 3 | POST /webhook with valid HMAC → pipeline dispatched → session persisted → webhook_events status updated to completed |
| M4: Admin API operational | Phase 4 | Full CRUD cycle for repositories, events, and sessions via admin API with auth |
| M5: Token lifecycle managed | Phase 5 | Token encrypted at rest, background refresh for installation tokens, reaper cleans stale sessions and events |
| M6: Production observability | Phase 6 | All structured log events and metrics firing, dashboard populated, alert rules active |
| M7: Verified under load | Phase 7 | Load test at max concurrency passes SLOs, behavioral identity verified, all regression tests pass |

## Dependencies

| Dependency | Type | Owner | Risk if Delayed |
|---|---|---|---|
| Phase 1 engine refactoring | Internal | Server team | All subsequent phases blocked — pipeline bridge cannot be built without parameterized engine |
| SQLite WAL mode compatibility | Internal | Server team | Low risk; aiosqlite + WAL is well-understood. If WAL causes issues, fall back to DELETE mode with reduced concurrency |
| Prometheus / OpenTelemetry infrastructure | External | Ops team | Metrics and alerts (Phase 6) degraded to log-based only. Recovery: deploy Prometheus sidecar or hosted metrics service after initial release |
| GitHub API token scopes | External | Repo admin | If tokens lack required scopes, pipeline outbound calls fail. Mitigation: document required scopes clearly in registration API |
| `opencode` CLI version compatibility | External | Server team | Docker image pins specific version; must rebuild on CLI updates. Mitigation: version as Docker build arg |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SQLite write contention under load (10 repos, 1 event/sec each) | Med | Med | Per-session `threading.Lock` serializes writes. Escalation: migrate to PostgreSQL (schema-compatible). |
| Thread pool exhaustion (all 20 workers occupied by long pipelines) | Low | High | Alert at 80% queue depth. Configurable `THREAD_POOL_MAX_WORKERS`. |
| Skills repository clone fails at startup, blocking readiness | Low | High | Retry with backoff; fall back to cached clone; volume mount for production. |
| Behavioral divergence between CLI and server pipeline paths | Low | High | Run acceptance criteria suite against both paths in CI before deploying server. |
| LLM provider outage causes pipeline failures | Med | Med | Pipeline failure alert fires but server stays healthy. Operators triage via runbook. |
| GitHub API rate limit exhaustion per token | Med | Med | Retry with backoff; log rate-limit headers; monitor via metric. |
| `versions.yaml` misconfiguration prevents server startup | Low | High | Validate at CI/build time; log clear error on parse failure. Server exits on invalid file. |
| Token re-encryption timeout at startup (large number of existing tokens) | Low | Low | Configurable timeout; partial re-encryption with remaining rows handled by `llmaw-admin reencrypt-tokens`. |

## Timeline (estimated for 2-person team)

| Phase | Start | End | Notes |
|---|---|---|---|
| Phase 1: Engine Refactoring | Week 1 | Week 1 | 5 person-days, no external dependencies |
| Phase 2: Server Foundation | Week 2 | Week 3 | 5 person-days, depends on Phase 1 |
| Phase 3: Webhook Pipeline | Week 3 | Week 4 | 6 person-days, depends on Phase 2 |
| Phase 4: Admin API | Week 4 | Week 5 | 4 person-days, depends on Phase 2 (parallel with Phase 3 possible) |
| Phase 5: Token & Background Tasks | Week 5 | Week 6 | 4 person-days, depends on Phase 2 (parallel with Phases 3-4 possible) |
| Phase 6: Observability | Week 6 | Week 7 | 4 person-days, depends on Phase 3 |
| Phase 7: Testing & Hardening | Week 7 | Week 8 | 5 person-days, depends on Phases 3-5 |
