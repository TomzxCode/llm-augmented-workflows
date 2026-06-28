---
artifact: telemetry.md
verdict: changes-requested
reviewed_at: "2026-06-28"
---

## Completeness

- Missing events for admin API failure responses. The spec defines 409 ALREADY_EXISTS (POST /admin/repositories), 404 NOT_FOUND (DELETE /admin/repositories), and 400 INVALID_INPUT (PATCH /admin/repositories), but only success events (`admin_repository_registered`, `admin_repository_deregistered`, `admin_repository_updated`) exist. Add `admin_repository_registration_failed`, `admin_repository_deregistration_failed`, and `admin_repository_update_failed` (or equivalent) to capture these error states.
- No event for pipeline submission failure. The spec documents that `run_in_executor` submission may fail when the thread pool queue is full, resulting in `webhook_events.status: failed`. Add a `pipeline_submission_failed` event to track this case separately from runtime execution failures.
- No version-tracking property in pipeline events. FR-10 (canary deployments) uses `repositories.version` to select agent configuration bundles, but no pipeline event records which version was used. Add a `version` property to `pipeline_dispatched` to enable monitoring of version-specific failure rates and latency.

## Measurability

No issues found. All success metrics are tied to concrete thresholds (`> 99%`, `< 5s`, `0 lost sessions`, `< 1%`), measurement methods are specified, and timeframes are defined.

## Actionability

No issues found. Alert thresholds are reasonable, counter metrics have clear investigation triggers, and alert severity (Pager / Ticket / Info) is correctly graded.

## Consistency

- `reencryption_progress` uses the spelling "reencryption" but the specification consistently uses "re-encryption" with a hyphen. Rename to `re_encryption_progress` for consistency with specification terminology.
- All other event names follow the `snake_case` entity_action pattern and match specification terminology.

## Coverage Gaps

- Admin API error states are not instrumented (see Completeness findings). Operators cannot distinguish between auth failures (which ARE instrumented via `admin_authentication_failure`) and semantic failures like duplicate registration or not-found.
- Pipeline submission failures are not instrumented (see Completeness findings). This is a distinct failure mode from pipeline execution failure and should be tracked separately.
- Dashboard could include a session reaper contention rate panel (`session_reaper_executed.contention_detected` ratio) to help operators tune SQLite WAL settings before contention becomes a throughput bottleneck.
