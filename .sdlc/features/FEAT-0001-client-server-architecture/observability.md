---
issue: "#16"
title: "Client/Server architecture"
status: in-review
revision: 1
---

# Observability: Client/Server architecture

## Overview

Monitor the hosted server's webhook ingestion pipeline, agent dispatch, token lifecycle, session management, and admin API through structured logging, counters, histograms, and health checks. Align with the telemetry plan's success metrics (webhook success rate >99%, p99 dispatch latency <5s, token refresh >99%) so operators can detect outages, diagnose failures, and verify SLOs before users are affected.

## Logging

### Webhook Ingestion

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | webhook_received | delivery_id, event_type, source_ip | HTTP POST received on /webhook |
| INFO | hmac_verification_completed | delivery_id, valid | HMAC-SHA256 verification finished |
| WARN | hmac_verification_failed | delivery_id, expected_prefix, actual_prefix | HMAC mismatch (contains only first 8 hex chars of each digest to avoid leaking the full secret) |
| INFO | dedup_check_completed | delivery_id, is_duplicate | Delivery ID lookup against webhook_events |
| INFO | repository_lookup_completed | owner, repo, found, active | Repository resolved from owner/repo in event payload |
| WARN | repository_not_found | owner, repo, delivery_id | Webhook arrived for an unregistered repository |
| INFO | unsupported_event_skipped | delivery_id, event_type | X-GitHub-Event is not a supported type |
| INFO | webhook_response | delivery_id, status_code, reason | Response sent to GitHub (accepted, skipped, error code) |
| WARN | invalid_payload | delivery_id, error_detail | Request body is not valid JSON (delivery_id = "none" if unparseable) |

### HTTP Middleware

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | http_request_received | method, path, client_ip, request_id | Every HTTP request reaching the server |
| INFO | http_request_completed | method, path, status_code, duration_ms, request_id | Response sent |
| WARN | rate_limit_exceeded | client_ip, endpoint, request_id | Request denied by token bucket |
| WARN | admin_authentication_failure | endpoint, client_ip, request_id | Admin API request with invalid/missing Authorization header |

### Pipeline Dispatch

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | pipeline_dispatched | delivery_id, repo_id, event_type, version | Agent pipeline queued in thread pool |
| WARN | pipeline_submission_failed | delivery_id, repo_id, event_type, reason: "thread_pool_queue_full" | Thread pool queue full, event accepted but not dispatched |
| INFO | pipeline_completed | delivery_id, repo_id, duration_ms, actions_taken | Agent pipeline finished successfully |
| ERROR | pipeline_failed | delivery_id, repo_id, error_type, error_message, duration_ms | Pipeline raised unhandled exception |

### Session Lifecycle

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | session_created | repo_id, subject_type, subject_id | First webhook event for a (repo, subject) pair |
| INFO | session_loaded | repo_id, subject_type, subject_id, conversation_length, session_expired | Existing session restored from SQLite |
| INFO | session_reaper_executed | deleted_count, contention_detected | Background session expiry reaper ran |
| WARN | session_reaper_contention | deleted_count | SQLITE_BUSY hit during reaper run |

### Token Refresh

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | token_refresh_started | repo_count | Background refresh cycle begins |
| INFO | token_refresh_completed | repo_id, owner, repo, auth_type | Single repository token refreshed successfully |
| WARN | token_refresh_failed | repo_id, owner, repo, auth_type, error_type, failure_count, repository_disabled | Token refresh failed for a repository |
| ERROR | repository_disabled | repo_id, owner, repo, failure_count | Repository auto-disabled after 3 consecutive refresh failures |

### Token Encryption

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | encryption_key_missing | none | TOKEN_ENCRYPTION_KEY not set, tokens stored in plaintext |
| INFO | re_encryption_progress | processed_count, total_count | Batch re-encryption progress during startup |
| ERROR | re_encryption_row_failed | row_id, error | Per-row re-encryption failure (corrupt ciphertext), row skipped |
| WARN | re_encryption_timeout | remaining_count | Re-encryption timed out before all rows processed |
| INFO | migration_from_plaintext | none | First start with TOKEN_ENCRYPTION_KEY after running without it |

### Graceful Shutdown

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | graceful_shutdown_started | in_flight_count, drain_timeout_s | SIGTERM received, shutdown begins |
| INFO | graceful_shutdown_completed | drained_count, cancelled_count, timed_out | Shutdown finished |
| WARN | graceful_shutdown_timed_out | cancelled_count | Drain timeout reached, remaining tasks cancelled |

### Admin API

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | admin_repository_registered | owner, repo, version, auth_type | POST /admin/repositories succeeded |
| INFO | admin_repository_deregistered | owner, repo | DELETE succeeded |
| INFO | admin_repository_updated | owner, repo, fields_changed | PATCH succeeded |
| WARN | admin_repository_registration_failed | owner, repo, error_code | POST returned error |
| WARN | admin_repository_deregistration_failed | owner, repo, error_code | DELETE returned error |
| WARN | admin_repository_update_failed | owner, repo, error_code | PATCH returned error |

### Version Configuration

| Log Level | Event | Fields | When |
|---|---|---|---|
| ERROR | versions_file_missing | path | versions.yaml not found at startup, server exits |
| ERROR | versions_file_malformed | path, parse_error | versions.yaml is invalid YAML, server exits |
| WARN | version_fallback | owner, repo, missing_version | Repository references a version key not in versions.yaml, falls back to v1 |

### Event Retention

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | event_retention_cleanup | deleted_count | Daily cleanup task deleted expired webhook_events rows |

## Metrics

### Webhook Requests Per Second

| Field | Value |
|---|---|
| Type | Counter |
| Description | Number of POST /webhook requests received, partitioned by outcome |
| Labels | outcome: accepted, skipped_unsupported, skipped_duplicate, error_auth, error_not_found, error_ratelimited, error_shutdown |
| Source | FastAPI middleware or route handler |

### Webhook Request Duration

| Field | Value |
|---|---|
| Type | Histogram |
| Description | Request duration from HTTP receipt to response sent (buckets: 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s) |
| Labels | outcome |
| Source | FastAPI middleware |

### Pipeline Dispatch Duration

| Field | Value |
|---|---|
| Type | Histogram |
| Description | Time from webhook receipt to pipeline invocation (webhook_events status: processing). Excludes LLM inference. Targets NFR-03. |
| Labels | event_type |
| Source | Pipeline bridge, comparing timestamps between webhook_received and pipeline_dispatched |

### Pipeline Execution Duration

| Field | Value |
|---|---|
| Type | Histogram |
| Description | Wall-clock time for agent pipeline execution (buckets: 1s, 5s, 15s, 30s, 60s, 120s, 300s) |
| Labels | event_type, version |
| Source | Pipeline bridge timer around run_in_executor |

### Pipeline Completion Count

| Field | Value |
|---|---|
| Type | Counter |
| Description | Pipeline outcomes for success rate calculation |
| Labels | status: completed, failed, skipped |
| Source | Pipeline bridge on completion |

### Thread Pool Queue Depth

| Field | Value |
|---|---|
| Type | Gauge |
| Description | Number of pipeline submissions currently queued in the thread pool waiting for a worker thread |
| Labels | none |
| Source | Thread pool queue size observation at /health check time |

### Pipeline Submission Failures

| Field | Value |
|---|---|
| Type | Counter |
| Description | Thread pool queue full, pipeline not dispatched |
| Labels | event_type |
| Source | Pipeline bridge on queue-full exception |

### Active Sessions

| Field | Value |
|---|---|
| Type | Gauge |
| Description | Number of non-expired sessions in the database |
| Labels | none |
| Source | SQLite query at /health check time |

### Active Repositories

| Field | Value |
|---|---|
| Type | Gauge |
| Description | Number of registered repositories with active=true |
| Labels | none |
| Source | SQLite query at /health check time |

### In-Flight Executions

| Field | Value |
|---|---|
| Type | Gauge |
| Description | Currently executing agent pipelines |
| Labels | none |
| Source | Thread pool state snapshot at /health check time |

### Events Processed Total

| Field | Value |
|---|---|
| Type | Counter |
| Description | Lifetime count of processed webhooks (accepted, not skipped) |
| Labels | none |
| Source | In-memory counter incremented on pipeline dispatch |

### Token Refresh Count

| Field | Value |
|---|---|
| Type | Counter |
| Description | Token refresh attempts partitioned by outcome |
| Labels | status: completed, failed, auth_type: installation, pat, user_token |
| Source | Token refresh background task |

### Token Refresh Failure Streak

| Field | Value |
|---|---|
| Type | Gauge |
| Description | Current consecutive failure count for each repository |
| Labels | owner, repo |
| Source | Token refresh background task (read from metadata._refresh_failure_count) |

### Graceful Shutdown Cancellations

| Field | Value |
|---|---|
| Type | Counter |
| Description | Number of in-flight tasks cancelled due to drain timeout during graceful shutdown |
| Labels | none |
| Source | Uvicorn lifespan handler on shutdown completion |

### Repositories Disabled

| Field | Value |
|---|---|
| Type | Counter |
| Description | Repositories auto-disabled by token refresh failure (3 consecutive failures) |
| Labels | auth_type |
| Source | Token refresh background task |

### Rate Limit Exceeded

| Field | Value |
|---|---|
| Type | Counter |
| Description | Requests denied by rate limiter |
| Labels | client_ip |
| Source | Rate limiting middleware |

### SQLite WAL File Size

| Field | Value |
|---|---|
| Type | Gauge |
| Description | Current size of the SQLite WAL file in bytes. Monitors write-ahead log growth that may indicate checkpoint pressure. |
| Labels | none |
| Source | Filesystem stat of SQLite WAL file at /health check time |

### SQLite Write Contention

| Field | Value |
|---|---|
| Type | Counter |
| Description | Number of SQLITE_BUSY retries observed across all database writes |
| Labels | operation: session_save, event_insert, reaper_delete, cleanup_delete |
| Source | Database wrapper layer that catches SQLITE_BUSY and retries |

### GitHub API Rate Limit Remaining

| Field | Value |
|---|---|
| Type | Gauge |
| Description | Minimum X-RateLimit-Remaining value observed across all repositories in the last scrape interval. Tracks headroom before retry storms. |
| Labels | none |
| Source | gh CLI call output parsed in pipeline bridge, exposed at /health check time |

### Session Reaper Deletion Count

| Field | Value |
|---|---|
| Type | Counter |
| Description | Cumulative count of expired sessions deleted by the background session reaper |
| Labels | none |
| Source | Session reaper task after each run |

### Admin API Requests

| Field | Value |
|---|---|
| Type | Counter |
| Description | Admin API request count partitioned by endpoint and status |
| Labels | endpoint, status: 2xx, 4xx |
| Source | Admin API route handlers |

### Version Configuration Errors

| Field | Value |
|---|---|
| Type | Counter |
| Description | Startup failures due to missing or malformed versions.yaml (server exits after incrementing) |
| Labels | error_type: file_missing, file_malformed |
| Source | Startup initialization phase |

### HMAC Verification Failures

| Field | Value |
|---|---|
| Type | Counter |
| Description | Webhook events where HMAC verification failed |
| Labels | outcome: invalid_signature, missing_header |
| Source | HMAC verifier middleware |

## Tracing

| Span Name | Service | Attributes | Parent Span |
|---|---|---|---|
| post_webhook | server | delivery_id, event_type, owner, repo | root |
| verify_hmac | server | delivery_id, valid | post_webhook |
| check_dedup | server | delivery_id, is_duplicate | post_webhook |
| lookup_repository | server | owner, repo, found | post_webhook |
| load_or_create_session | server | repo_id, subject_type, subject_id, conversation_length | post_webhook |
| dispatch_pipeline | server | delivery_id, repo_id, event_type | post_webhook |
| execute_pipeline | server | delivery_id, repo_id | dispatch_pipeline |
| refresh_token | server | repo_id, auth_type | root (async background task) |
| reencrypt_tokens | server | processed_count, total_count | root (startup phase) |

## Health Checks

| Check | Type | Endpoint / Method | Healthy Condition |
|---|---|---|---|
| Server process | Liveness | GET /health (or container health check: `curl -f http://localhost:8080/health`) | Returns 200 with status: "healthy". Fails if process is dead or stuck. |
| Readiness | Readiness | GET /health | All startup phases complete (versions.yaml loaded, skills repository cloned, token re-encryption if applicable, schema migrations applied), SQLite reachable, and the server is not in graceful-shutdown state. |
| SQLite connectivity | Readiness | Implicit in /health handler | SQLite query (SELECT 1) succeeds |
| Graceful drain | Liveness | /health during shutdown | Returns 503 when shutdown_event is set |
| GitHub API reachability | Readiness (optional) | GET /health via dependency probe | Server can reach api.github.com (TCP connect). Degradation detected by pipeline failure alerts. Excluded from required readiness to avoid cascading failures when GitHub has an outage. |
| LLM API reachability | Readiness (optional) | GET /health via dependency probe | Server can reach the configured LLM API endpoint (TCP connect). Degradation detected by pipeline failure alerts. Excluded from required readiness to avoid cascading failures when the LLM provider has an outage. |

## Alerts

### High Pipeline Failure Rate

| Field | Value |
|---|---|
| Condition | rate(pipeline_failed_total[5m]) / rate(pipeline_completed_total[5m]) > 0.05 |
| Severity | Critical |
| For | 5 minutes |
| Runbook | 1. Check pipeline_failed logs for error_type to identify root cause. 2. If LLM API errors, check provider status. 3. If engine errors, check for code regression in recent deploy. 4. If thread pool saturation, check pipeline_submission_failed count. |
| Notification | PagerDuty, Slack #ops |

### Repository Auto-Disabled

| Field | Value |
|---|---|
| Condition | increase(repositories_disabled_total[5m]) > 0 |
| Severity | Critical |
| For | 1 minute |
| Runbook | 1. Identify affected repository from metric labels. 2. Check token_refresh_failed logs for error_type. 3. If network error, verify outbound connectivity. 4. If auth error, verify GitHub App installation or PAT validity. 5. Re-enable via PATCH /admin/repositories/{owner}/{repo} with active: true. |
| Notification | PagerDuty, Slack #ops |

### Webhook Processing Degraded

| Field | Value |
|---|---|
| Condition | rate(webhook_requests_total{outcome=~"error_.*"}[5m]) / rate(webhook_requests_total[5m]) > 0.01 |
| Severity | Warning |
| For | 5 minutes |
| Runbook | 1. Check webhook_response logs for error code distribution. 2. If INVALID_SIGNATURE spikes, verify webhook secret config. 3. If RATE_LIMITED, check rate_limit_exceeded per client_ip. 4. If UNKNOWN_REPOSITORY, check repository registration. |
| Notification | Slack #ops |

### High HMAC Failure Rate

| Field | Value |
|---|---|
| Condition | rate(hmac_verification_failures_total[1h]) / rate(webhook_requests_total[1h]) > 0.01 |
| Severity | Warning |
| For | 1 hour |
| Runbook | 1. Check hmac_verification_failed logs. 2. Compare expected vs actual signature prefix. 3. Verify webhook secret matches repository registration. 4. If no config change, investigate possible forgery attempt. |
| Notification | Slack #ops (ticket) |

### Token Refresh Failures Spiking

| Field | Value |
|---|---|
| Condition | rate(token_refresh_failed_total[15m]) > 5 |
| Severity | Warning |
| For | 15 minutes |
| Runbook | 1. Check token_refresh_failed logs by error_type. 2. If network errors, check outbound connectivity. 3. If auth errors, check GitHub App private key and installation status. 4. Monitor repository_disabled counter. |
| Notification | Slack #ops |

### Thread Pool Saturated

| Field | Value |
|---|---|
| Condition | increase(pipeline_submission_failures_total[5m]) > 0 |
| Severity | Warning |
| For | 5 minutes |
| Runbook | 1. Check in_flight_executions gauge. 2. If persistently at max, increase THREAD_POOL_MAX_WORKERS if CPU headroom allows. 3. Check if pipelines are stuck (long execution durations). |
| Notification | Slack #ops |

### Graceful Shutdown Had Cancellations

| Field | Value |
|---|---|
| Condition | increase(graceful_shutdown_cancelled_total[30d]) > 0 |
| Severity | Info |
| For | 1 hour |
| Runbook | 1. Check graceful_shutdown_completed logs for cancelled_count and timed_out. 2. Consider increasing GRACEFUL_DRAIN_TIMEOUT_SECONDS. 3. Review if pipeline durations are routinely exceeding drain timeout. |
| Notification | Slack #ops (dashboard note) |

### Session Reaper Large Cleanup

| Field | Value |
|---|---|
| Condition | increase(session_reaper_deletions_total[1h]) > 1000 |
| Severity | Info |
| For | At event time (check on reaper run) |
| Runbook | 1. Check session_reaper_executed logs for deleted_count. 2. Review SESSIONS_MAX_AGE_HOURS. 3. If count is unexpectedly high, investigate possible session creation bug. |
| Notification | Slack #ops (dashboard note) |

### Version Configuration Error

| Field | Value |
|---|---|
| Condition | increase(versions_file_errors_total[5m]) > 0 |
| Severity | Critical |
| For | 1 minute |
| Runbook | 1. Check versions_file_missing or versions_file_malformed logs. 2. Verify /etc/llmaw/versions.yaml exists and is valid YAML. 3. Restart server after fixing the file. Server will not start without valid versions.yaml. |
| Notification | PagerDuty, Slack #ops |

## SLOs

| SLO | Target | SLI | Measurement Window |
|---|---|---|---|
| Webhook acceptance availability | 99.5% | Proportion of HTTP POST /webhook requests that return a 200 (including skipped/duplicate) and not a 5xx error. Measured over all webhook requests. | Rolling 30 days |
| Webhook dispatch latency (p99) | 5 seconds | Time from HTTP receipt to pipeline invocation (webhook_events status: processing). Excludes LLM inference. | Rolling 7 days |
| Webhook dispatch latency (p50) | 1 second | Same measurement point as p99. | Rolling 7 days |
| Pipeline success rate | 99% | (pipeline_completed / (pipeline_completed + pipeline_failed)) per day. | Rolling 7 days |
| Token refresh success rate | 99% | Successful refreshes / total refresh attempts per day. | Rolling 7 days |
| Session durability on restart | 0 lost committed sessions | Sessions before restart vs. after restart on same Docker volume. | Per restart event |
| Dispatch latency at max concurrency (p99) | 5 seconds | Per-repository dispatch latency measured when 10 repositories are concurrently active. Same measurement point as webhook dispatch latency SLO. | Rolling 7 days |
| Aggregate event throughput | 10 events/second | Sustained event rate across all repositories averaged over 5-minute windows. | Rolling 7 days |

## Infrastructure Requirements

| Requirement | Type | Notes |
|---|---|---|
| Add structured logging middleware to FastAPI | Log | structlog already specified in architecture; ensure every middleware and route handler emits structured events |
| Add health check to container orchestrator | Health | Ensure Docker HEALTHCHECK or orchestrator liveness/readiness probes point to GET /health |
| Instrument thread pool monitoring | Metric | Track queue depth, active thread count, rejected submissions |
| *Expose Prometheus metrics endpoint* | Metric | Add /metrics endpoint (e.g., prometheus-fastapi-instrumentator). The specification scopes out Prometheus/OTEL as out of scope, relying on structured logs alone. However, the PromQL-based alert conditions defined in this plan (error rate ratios, latency histograms) require a Prometheus-compatible metrics backend. This is an additive dependency not covered by NFR-07's single-container constraint — add a Prometheus sidecar or use a hosted metrics service. |
| *Configure Prometheus to scrape /metrics* | Metric | Prometheus target configuration (additive dependency per note above) |
| *Build Server Operations Dashboard* | Dashboard | Grafana dashboard with panels for throughput, latency, error rates, active sessions, token refresh, rate limiting (additive dependency per note above) |
| *Configure alert routing* | Alert | PagerDuty for Critical alerts, Slack for Warning/Info (additive dependency per note above) |
| *Emit trace spans across webhook processing path* | Trace | OpenTelemetry SDK integration; propagate trace_id through thread pool to pipeline execution (additive dependency per note above) |
| *Add OpenTelemetry span processor for trace export* | Trace | Configure OLTP exporter or Jaeger endpoint (additive dependency per note above) |

## Out of Scope

- LLM inference latency and token usage: tracked by LLM provider telemetry and CLI-based engine metrics, not server-specific
- GitHub API response times for outbound calls: surfaced in existing engine structured logging, not server-specific
- Per-repository storage growth metrics: 90-day retention window and cleanup task prevent unbounded growth; unnecessary at single-container scale
- Client-side observability (browser metrics, user interaction): no browser client exists for this feature
- Prometheus/OpenTelemetry metrics infrastructure: the specification scoped this out, relying on structured logs alone. The PromQL-based alert conditions in this plan require a Prometheus-compatible backend, which is an additive dependency. Items marked with * in Infrastructure Requirements are additive and would require updating the specification or accepting the additional dependency.
