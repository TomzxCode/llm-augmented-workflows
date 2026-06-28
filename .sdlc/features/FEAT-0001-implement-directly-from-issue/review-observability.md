---
artifact: observability
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Completeness

**Missing alert for infrastructure step failures:** The spec identifies multiple infrastructure failure modes (triage skill crash, label application failure via `gh issue edit`, workflow dispatch error, missing outcome YAML). These are captured by the `workflow_step_failed` log event but have no dedicated alert. The "Express Path Silently Degraded" alert only triggers on total inactivity over 7 days, not on individual infrastructure failures. A burst of transient failures that self-recover within the 7-day window would go unalerted. Either add an alert for infrastructure failure rate (e.g., > 3 workflow_step_failed events in a rolling 24h window) or explicitly document why these are out of scope for alerting.

**Missing timeout alert:** `express_path_timeout` is logged as ERROR but has no corresponding alert. A single timeout event is visible only through log inspection. The aggregated failure rate alert would catch repeated timeouts, but a single timeout that delays a feature by 15+ minutes goes unnotified. Add an alert for individual timeout events, or document the decision to not alert on them.

## Actionability

No issues found. All 4 alerts have runbooks with concrete diagnostic and resolution steps. Logs are structured with typed fields. Metrics include labels for narrowing down issues. The "post-hoc" nature of alerts is explicitly documented in Out of Scope and acceptable for V1 volume.

## Consistency

**SLO #1 duplicates telemetry success metric:** The observability SLO "Express implementation success rate >= 80%" (Rolling 30 days, formula: `llmaw:express-done / (llmaw:express-done + llmaw:express-failed)`) is identical to the telemetry plan's "Express implementation success rate > 80%" (Monthly, formula: `gh issue list --label llmaw:express-done / (llmaw:express-done + llmaw:express-failed)`). The same metric with the same target and nearly identical measurement method is defined in two places. Clarify which document owns this metric:
- If observability owns it: remove or reference it from telemetry
- If telemetry owns it: reference it from observability rather than redefining

**Express-path timeout threshold defined only in spec:** The spec defines `defaults.express.timeout_minutes: 15` but the observability plan's `express_path_timeout` log and "Express Path Silently Degraded" alert refer to a timeout without specifying which timeout (the 15-min implementation timeout or a longer 7-day inactivity window). Add the timeout threshold to the log definition or cross-reference the spec's `defaults.express.timeout_minutes`.

## Coverage Gaps

No issues found. Error states (implementation failure, timeout, label removal, classification bypass) are covered. Background processes and async operations are not applicable (synchronous workflow). Dependencies (GitHub API, LLM API) are monitored through health checks and failure events. Saturation metrics for external APIs (GitHub rate limits, LLM API rate limits) are out of scope for V1, which is acceptable.

## Overlap with Telemetry

**Duplicate thresholds:** Three observability alerts define the same thresholds as telemetry counter metrics:
- "Express Implementation Failure Rate Exceeds Threshold" (> 20%) duplicates telemetry's "Express implementation failure rate" (> 20%)
- "Token Efficiency Below Target" (> 60% of full pipeline) duplicates telemetry's "Token savings below target" (> 60%)
- "Classification Comment Spam" (> 5 per issue) duplicates telemetry's "Classification comment spam" (> 5 per issue)

These are currently defined in both documents with identical thresholds. If one is updated without the other, the documents will drift. Move the threshold definitions to one owner (suggest: telemetry defines the concern/threshold, observability references it), or add a note in each alert that the threshold must stay in sync with the telemetry plan.

**Shared data sources not explicitly documented:** Observability metrics (`express_flow_match_total`, `express_classification_count`, `express_token_consumption_total`) share event data with telemetry events (`implementation_completed`, `issue_classified`). The relationship between system-health metrics and business-analytics events is not documented. Add a note in each plan or in the observability document clarifying which system owns which metric and how they relate.
