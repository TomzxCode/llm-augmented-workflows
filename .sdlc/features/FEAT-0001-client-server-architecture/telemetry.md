---
issue: "#16"
title: "Client/Server architecture"
status: approved
---

# Telemetry: Client/Server architecture

## Overview

Measure adoption, reliability, and performance of the hosted server execution model. Track webhook processing throughput, success rates, pipeline dispatch latency, admin API usage, token refresh health, and session lifecycle. These metrics answer whether the server is a viable replacement for GitHub Actions execution and whether operators can manage it without surprises.

## Success Metrics

| Metric | Target | Measurement Method | Timeframe |
|---|---|---|---|
| Webhook processing success rate | > 99% | `completed` events / (completed + failed) events per day | Daily rolling 7-day window |
| Webhook dispatch latency (p99) | < 5s (excluding LLM inference) | Time from HTTP receipt to `webhook_events.status: processing` | Daily rolling 7-day window |
| Webhook dispatch latency (p50) | < 1s (excluding LLM inference) | Same measurement point as p99 | Daily rolling 7-day window |
| Token refresh success rate | > 99% | Successful refreshes / total refresh attempts per day | Daily |
| Admin API uptime contribution | No server restarts caused by admin operations | Count of unplanned restarts attributed to admin API usage | Monthly |
| Session durability on restart | 0 lost sessions per restart | Sessions before restart vs. after restart on same volume | Per restart event |
| Rate-limited requests rate | < 1% of all webhook requests | Rate-limited responses / total webhook responses per day | Daily |

## User Funnel

The primary user is an operator managing the server for their repositories. End-user impact is indirect via uninterrupted automation.

| Step | Event | Entry Criteria | Exit Criteria |
|---|---|---|---|
| 1. Webhook Received | `webhook_received` | GitHub delivers POST to /webhook | HMAC verification completes |
| 2. Request Authenticated | `hmac_verification_completed` | HMAC verification begins | Valid signature accepted |
| 3. Delivery Deduplicated | `dedup_check_completed` | Delivery ID lookup begins | No duplicate found |
| 4. Repository Identified | `repository_lookup_completed` | Repository lookup begins | Owner/repo found in database |
| 5. Session Ready | `session_loaded` / `session_created` | Session load or create begins | Session ready for pipeline |
| 6. Pipeline Dispatched | `pipeline_dispatched` | Pipeline dispatch begins | Agent pipeline thread started |
| 7. Pipeline Completed | `pipeline_completed` / `pipeline_failed` | Agent pipeline execution completes | Status written to webhook_events |

## Analytics Events

### webhook_received

**Trigger:** HTTP POST received on /webhook before any processing
**Location:** FastAPI route handler in webhook router

| Property | Type | Required | Description |
|---|---|---|---|
| delivery_id | string | Yes | X-GitHub-Delivery header value |
| event_type | string | Yes | X-GitHub-Event header value (push, pull_request, issue_comment, issues) |
| source | string | Yes | Always "server" |

### hmac_verification_completed

**Trigger:** HMAC-SHA256 verification finished
**Location:** HMAC verifier middleware

| Property | Type | Required | Description |
|---|---|---|---|
| delivery_id | string | Yes | X-GitHub-Delivery header value |
| valid | boolean | Yes | Whether HMAC signature matched |
| source | string | Yes | Always "server" |

### dedup_check_completed

**Trigger:** Delivery ID dedup lookup finished
**Location:** Webhook router after database query

| Property | Type | Required | Description |
|---|---|---|---|
| delivery_id | string | Yes | X-GitHub-Delivery header value |
| is_duplicate | boolean | Yes | Whether this delivery was already processed |
| source | string | Yes | Always "server" |

### repository_lookup_completed

**Trigger:** Repository lookup by owner/repo finished
**Location:** Webhook router after database query

| Property | Type | Required | Description |
|---|---|---|---|
| owner | string | Yes | GitHub owner |
| repo | string | Yes | GitHub repository |
| found | boolean | Yes | Whether repository is registered |
| active | boolean | No | Whether repository is active (only when found) |
| source | string | Yes | Always "server" |

### session_loaded

**Trigger:** Existing session loaded from SQLite
**Location:** Session store

| Property | Type | Required | Description |
|---|---|---|---|
| repo_id | string | Yes | Repository UUID |
| subject_type | string | Yes | "issue", "pull_request", or "push" |
| subject_id | integer | Yes | Issue/PR number (0 for push) |
| conversation_length | integer | Yes | Number of messages in history |
| session_expired | boolean | Yes | Whether session was expired and re-created |
| source | string | Yes | Always "server" |

### session_created

**Trigger:** New session created for first webhook event on a subject
**Location:** Session store

| Property | Type | Required | Description |
|---|---|---|---|
| repo_id | string | Yes | Repository UUID |
| subject_type | string | Yes | "issue", "pull_request", or "push" |
| subject_id | integer | Yes | Issue/PR number (0 for push) |
| source | string | Yes | Always "server" |

### pipeline_dispatched

**Trigger:** Agent pipeline dispatched to thread pool
**Location:** Pipeline bridge

| Property | Type | Required | Description |
|---|---|---|---|
| delivery_id | string | Yes | X-GitHub-Delivery header value |
| repo_id | string | Yes | Repository UUID |
| event_type | string | Yes | GitHub event type |
| source | string | Yes | Always "server" |

### pipeline_completed

**Trigger:** Agent pipeline execution finished successfully
**Location:** Pipeline bridge after run_in_executor returns

| Property | Type | Required | Description |
|---|---|---|---|
| delivery_id | string | Yes | X-GitHub-Delivery header value |
| repo_id | string | Yes | Repository UUID |
| duration_ms | integer | Yes | Wall-clock execution time in ms |
| actions_taken | integer | Yes | Number of outbound actions dispatched |
| source | string | Yes | Always "server" |

### pipeline_failed

**Trigger:** Agent pipeline execution failed
**Location:** Pipeline bridge on exception

| Property | Type | Required | Description |
|---|---|---|---|
| delivery_id | string | Yes | X-GitHub-Delivery header value |
| repo_id | string | Yes | Repository UUID |
| error_type | string | Yes | Exception class name |
| error_message | string | Yes | Exception message (sanitized, no secrets) |
| duration_ms | integer | Yes | Wall-clock execution time before failure |
| source | string | Yes | Always "server" |

### token_refresh_started

**Trigger:** Background token refresh cycle begins
**Location:** Token refresh background task

| Property | Type | Required | Description |
|---|---|---|---|
| repo_count | integer | Yes | Number of repositories needing refresh |
| source | string | Yes | Always "server" |

### token_refresh_completed

**Trigger:** Token refresh succeeded for a repository
**Location:** Token refresh background task

| Property | Type | Required | Description |
|---|---|---|---|
| repo_id | string | Yes | Repository UUID |
| owner | string | Yes | GitHub owner |
| repo | string | Yes | GitHub repository |
| auth_type | string | Yes | "installation", "pat", or "user_token" |
| source | string | Yes | Always "server" |

### token_refresh_failed

**Trigger:** Token refresh failed for a repository
**Location:** Token refresh background task

| Property | Type | Required | Description |
|---|---|---|---|
| repo_id | string | Yes | Repository UUID |
| owner | string | Yes | GitHub owner |
| repo | string | Yes | GitHub repository |
| auth_type | string | Yes | "installation", "pat", or "user_token" |
| error_type | string | Yes | Categorised error (network, github_api, auth) |
| failure_count | integer | Yes | Consecutive failure count after this attempt |
| repository_disabled | boolean | Yes | Whether active was set to false (>3 failures) |
| source | string | Yes | Always "server" |

### rate_limit_exceeded

**Trigger:** Request denied by in-memory token bucket
**Location:** Rate limiting middleware

| Property | Type | Required | Description |
|---|---|---|---|
| client_ip | string | Yes | Requesting IP address |
| endpoint | string | Yes | Requested path |
| source | string | Yes | Always "server" |

### unsupported_event_skipped

**Trigger:** X-GitHub-Event is not a supported type
**Location:** Webhook router

| Property | Type | Required | Description |
|---|---|---|---|
| delivery_id | string | Yes | X-GitHub-Delivery header value |
| event_type | string | Yes | Unsupported event type name |
| source | string | Yes | Always "server" |

### graceful_shutdown_started

**Trigger:** SIGTERM received, shutdown sequence begins
**Location:** Uvicorn lifespan handler

| Property | Type | Required | Description |
|---|---|---|---|
| in_flight_count | integer | Yes | Number of tasks in flight at shutdown start |
| drain_timeout_s | integer | Yes | Configured drain timeout in seconds |
| source | string | Yes | Always "server" |

### graceful_shutdown_completed

**Trigger:** Shutdown sequence finished (drained or timed out)
**Location:** Uvicorn lifespan handler

| Property | Type | Required | Description |
|---|---|---|---|
| drained_count | integer | Yes | Tasks that completed during drain |
| cancelled_count | integer | Yes | Tasks cancelled on drain timeout |
| timed_out | boolean | Yes | Whether drain timeout was reached |
| source | string | Yes | Always "server" |

### admin_repository_registered

**Trigger:** POST /admin/repositories succeeded
**Location:** Admin API route handler

| Property | Type | Required | Description |
|---|---|---|---|
| owner | string | Yes | GitHub owner |
| repo | string | Yes | GitHub repository |
| version | string | Yes | Agent version assigned |
| auth_type | string | Yes | "pat", "installation", or "user_token" |
| source | string | Yes | Always "server" |

### admin_repository_deregistered

**Trigger:** DELETE /admin/repositories/{owner}/{repo} succeeded
**Location:** Admin API route handler

| Property | Type | Required | Description |
|---|---|---|---|
| owner | string | Yes | GitHub owner |
| repo | string | Yes | GitHub repository |
| source | string | Yes | Always "server" |

### admin_repository_updated

**Trigger:** PATCH /admin/repositories/{owner}/{repo} succeeded
**Location:** Admin API route handler

| Property | Type | Required | Description |
|---|---|---|---|
| owner | string | Yes | GitHub owner |
| repo | string | Yes | GitHub repository |
| fields_changed | array of strings | Yes | List of changed field names |
| source | string | Yes | Always "server" |

### session_reaper_executed

**Trigger:** Background session expiry reaper ran
**Location:** Scheduled reaper task

| Property | Type | Required | Description |
|---|---|---|---|
| deleted_count | integer | Yes | Number of expired sessions deleted |
| contention_detected | boolean | Yes | Whether SQLITE_BUSY was hit |
| source | string | Yes | Always "server" |

### event_retention_cleanup

**Trigger:** Daily webhook event retention cleanup ran
**Location:** Scheduled cleanup task

| Property | Type | Required | Description |
|---|---|---|---|
| deleted_count | integer | Yes | Number of events older than retention window |
| source | string | Yes | Always "server" |

### health_check

**Trigger:** GET /health request received
**Location:** Health endpoint route handler

| Property | Type | Required | Description |
|---|---|---|---|
| status | string | Yes | "healthy" or "unhealthy" |
| active_repositories | integer | Yes | Count of active repositories |
| active_sessions | integer | Yes | Count of non-expired sessions |
| in_flight_executions | integer | Yes | Currently executing pipelines |
| events_processed_total | integer | Yes | Lifetime processed events |
| uptime_seconds | integer | Yes | Seconds since process start |
| source | string | Yes | Always "server" |

### reencryption_progress

**Trigger:** Token re-encryption batch progress logged during startup
**Location:** Startup initialization phase

| Property | Type | Required | Description |
|---|---|---|---|
| processed_count | integer | Yes | Rows processed so far |
| total_count | integer | Yes | Total rows to process |
| source | string | Yes | Always "server" |

### admin_authentication_failure

**Trigger:** Admin API request with missing or invalid Authorization header
**Location:** Admin API auth middleware

| Property | Type | Required | Description |
|---|---|---|---|
| endpoint | string | Yes | Requested admin path |
| source | string | Yes | Always "server" |

## Counter Metrics

| Metric | Concern | Threshold |
|---|---|---|
| Token refresh failure rate (per repo) | Repository may be silently disabled after 3 consecutive failures | Any single repo exceeds 2 consecutive failures |
| HMAC verification failure rate | Possible misconfigured webhook secret or attempted forgery | > 1% of webhook events per repository per day |
| Pipeline failure rate | Agent or pipeline errors degrading automation quality | > 5% of dispatched pipelines per day |
| Rate-limited request rate per IP | Potential webhook storm or misconfigured sender | > 100 events limited per IP per hour |
| Session creation vs load ratio | Possible session expiry issues causing unnecessary re-creation | > 20% of session lookups result in new session creation |
| Graceful shutdown cancellation count | Draining timeout may be too short | > 0 cancelled tasks in any shutdown event |
| Repository not found rate | Webhooks arriving for unregistered repos | > 5% of webhook events per day |

## Telemetry Requirements

| Requirement | Type | Notes |
|---|---|---|
| Add structured logging to all middleware and route handlers | Infrastructure | Use structlog as specified in the architecture; all events above are structlog log calls emitted as JSON |
| Expose /health endpoint counters via health check response | Infrastructure | Already defined in spec; counts are live metrics from in-memory counters |
| Add gauge metric for in-flight executions | Event | Track via thread pool state at /health check time |
| Add gauge metric for active sessions | Event | Count from SQLite query on /health check |
| Add gauge metric for active repositories | Event | Count from SQLite query on /health check |
| Build a dashboard showing webhook throughput, latency, error rates | Dashboard | See Dashboards and Alerts section |
| Alert on repository disabled by token refresh failure | Alert | Pager-worthy; operator must investigate and re-enable |
| Alert on pipeline failure rate exceeding threshold | Alert | Investigate agent or pipeline issues |
| Log rate limit events with client IP and endpoint | Event | Diagnose misconfigured webhook sources |

## Dashboards and Alerts

- **Dashboard:** Server Operations Dashboard showing:
  - Webhook throughput (events/minute by event_type)
  - Webhook dispatch latency (p50, p95, p99, p99.9 over the last hour)
  - Pipeline completion rate (completed / failed / skipped stacked over time)
  - Active repositories and sessions (current count)
  - Token refresh success rate (rolling 7-day)
  - Top 5 repositories by event volume
  - Rate-limited request count per IP (last hour)
  - Graceful shutdown events (last 30 days)
  - Session reaper and event cleanup activity (deleted count per run)

- **Alerts:**
  - **Pager:** Repository auto-disabled by token refresh failure (investigate and re-enable via admin API)
  - **Pager:** Pipeline failure rate > 5% over 5 minutes (potential agent regression)
  - **Ticket:** HMAC verification failure rate > 1% per repo over 1 hour (check webhook secret)
  - **Ticket:** Rate-limited requests > 100/IP over 1 hour (investigate webhook source)
  - **Info:** Graceful shutdown with cancelled tasks (consider increasing drain timeout)
  - **Info:** Session reaper deletes > 1000 sessions in a single run (check TTL config)

## Out of Scope

- LLM inference latency and token usage: these are tracked by the LLM provider's own telemetry and the existing CLI-based engine metrics. The server wraps the same engine and should not duplicate provider-level instrumentation.
- Per-repository event payload sizes and storage growth: the 90-day retention window and cleanup task prevent unbounded growth; deeper storage analytics would require dumping SQLite size metrics, which is unnecessary at single-container scale.
- GitHub API response times for outbound calls: these are surfaced in the existing engine's structured logging and are not server-specific.
