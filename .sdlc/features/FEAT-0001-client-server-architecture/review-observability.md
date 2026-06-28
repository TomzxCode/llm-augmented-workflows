---
artifact: observability.md
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Completeness

1. **Missing INVALID_PAYLOAD log event.** The specification defines a 400 `INVALID_PAYLOAD` error when the webhook body is not valid JSON, but no structured log event covers this case. Add an entry to the Webhook Ingestion logging table for `invalid_payload` with fields `delivery_id` (or `none` if unparseable) and `error_detail`.

2. **`graceful_shutdown_cancelled_total` metric referenced but not defined.** The "Graceful Shutdown Had Cancellations" alert references `increase(graceful_shutdown_cancelled_total[30d])` but no corresponding counter exists in the Metrics section. Define the counter or source the alert from `graceful_shutdown_completed.cancelled_count` in logs instead.

3. **No health checks for outbound dependencies.** The health checks cover process liveness, readiness, and SQLite connectivity but not critical outbound dependencies: GitHub API reachability and LLM API reachability. Degradation of either will silently cause pipeline failures until the "High Pipeline Failure Rate" alert fires. Add optional dependency health checks (or document them as intentionally excluded with rationale).

4. **Missing SLOs for concurrency and throughput.** The specification sets targets of 10 concurrent active repositories and 10 events/second throughput, but the SLOs section does not include corresponding SLOs for either. Add SLOs for per-repository dispatch latency under maximum concurrency and aggregate throughput.

## Actionability

1. **Pipeline Submission Failures metric has no labels.** The counter has `labels: none`. When the thread pool is saturated, operators cannot tell which event type or repo is driving the submissions. Add an `event_type` (or `repo_id` cardinality-permitting) label to narrow down the source.

2. **HMAC Verification Failures metric has no labels.** The counter has `labels: none`. Adding an `outcome` label (`invalid_signature`, `missing_header`) would help diagnose whether failures are caused by misconfiguration or a potential forgery attempt.

## Consistency

1. **Spec scopes out metrics infrastructure; observability plan assumes it.** The specification's Out of Scope section states "No Prometheus, OpenTelemetry, or statsd export is specified. Structured logs are the observability channel." The observability plan's Infrastructure Requirements assume Prometheus scraping, a `/metrics` endpoint, and an OpenTelemetry span processor. These are additive requirements the spec did not anticipate and may conflict with NFR-07's single-container constraint. Either align the plan to work within structured logs only, or update the specification to reflect the new dependency on a Prometheus stack.

2. **Alert metric naming convention drift.** Most alert conditions reference metrics using a `_total` suffix convention (e.g., `webhook_requests_total`, `pipeline_failed_total`). The "Session Reaper Large Cleanup" alert uses `session_reaper_deleted_count` instead (no `_total` suffix) and the "High HMAC Failure Rate" alert references `hmac_verification_failures_total` while the metrics section names the counter "HMAC Verification Failures" with no explicit Prometheus name. Standardize alert metric references to match the defined metric names and ensure consistent suffix conventions.

## Coverage Gaps

1. **Thread pool queue depth not instrumented.** The Infrastructure Requirements section lists "Track queue depth, active thread count, rejected submissions" but the Metrics section only defines `In-Flight Executions` (active thread count) and `Pipeline Submission Failures` (rejected submissions). Queue depth is missing. Add a gauge for thread pool queue depth so operators can observe saturation trends before submissions are rejected.

2. **SQLite health monitoring is limited to `SELECT 1` connectivity.** No metrics cover SQLite WAL file size, write latency, or `SQLITE_BUSY` contention rate beyond a log event for the session reaper. Add a gauge for WAL file size or a counter for `SQLITE_BUSY` retries observed across all writes.

3. **GitHub API rate limit headroom not monitored.** The specification identifies GitHub API rate limiting as a risk (Risks item 6), with retry-and-log as the mitigation. No metric tracks remaining rate limit capacity for each repository's token. Consider surfacing the `X-RateLimit-Remaining` header value as a gauge per repository (or aggregate) so operators can proactively rotate tokens nearing exhaustion.

## Overlap with Telemetry

No issues found. The logging sections in both documents intentionally cover the same structured events. The telemetry plan owns business analytics; the observability plan owns system health metrics, alerts, and SLOs. The separation is clear.
