---
issue: "#17"
title: "Implement directly from issue"
status: draft
---

# Observability: Implement directly from issue

## Overview

The express path is a GitHub Actions workflow automation with no traditional services, HTTP endpoints, or databases. Observability relies on structured workflow logs, label-based state queries, and LLM token usage telemetry. The primary observability goals are detecting implementation failures, monitoring classification accuracy, verifying token efficiency targets, and ensuring the express path does not silently degrade.

## Logging

### Workflow Execution

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | flow_matched | rule_name, issue_number, event_type, label_name | An express flow rule matches an incoming event |
| INFO | triage_completed | issue_number, verdict, complexity, source | Triage-issue skill finishes with a verdict |
| INFO | express_eligible_set | issue_number, complexity | `llmaw:express-eligible` label is applied to an issue |
| INFO | implementation_started | issue_number, trigger, complexity, issue_body_length | `create-implementation` agent step begins |
| INFO | implementation_completed | issue_number, pr_number, trigger, token_input, token_output, duration_seconds | `create-implementation` succeeds and creates a PR |
| WARN | classification_bypassed | issue_number, label | `llmaw:quick-implement` is applied, skipping triage classification |
| WARN | express_eligible_removed | issue_number, label_removed, remaining_labels | A human removes an express-path label, triggering fallback |
| ERROR | implementation_failed | issue_number, trigger, complexity, failure_reason, token_input, token_output, duration_seconds | `create-implementation` returns `verdict: failed` |
| ERROR | workflow_step_failed | issue_number, step_name, error_type, error_message | An upstream infrastructure step fails (crash, timeout, label failure) |
| ERROR | express_path_timeout | issue_number, timeout_minutes | Express path exceeds the configured timeout |

### Label State Transitions

| Log Level | Event | Fields | When |
|---|---|---|---|
| INFO | label_applied | issue_number, label_name, actor | Any `llmaw:*` label is applied |
| INFO | label_removed | issue_number, label_name, actor | Any `llmaw:*` label is removed |
| WARN | terminal_label_reached | issue_number, label | `llmaw:express-done` or `llmaw:express-failed` is set (issue will not be re-processed without human intervention) |

## Metrics

### express_flow_match_total

| Field | Value |
|---|---|
| Type | Counter |
| Description | Total number of times an express flow rule matches an event |
| Labels | rule_name (`express-implement-from-eligible`, `express-quick-implement`), event_type (`issues:labeled`), outcome (`approved`, `failed`) |
| Source | `flows.yml` on_outcome handler (shell step emitting to GITHUB_STEP_SUMMARY) |

### express_implementation_duration_seconds

| Field | Value |
|---|---|
| Type | Histogram |
| Description | Wall-clock duration of the `create-implementation` agent step |
| Labels | trigger (`classification`, `manual`), complexity (`low`, `medium`, `high`), outcome (`approved`, `failed`) |
| Source | `create-implementation` skill outcome YAML |

### express_token_consumption_total

| Field | Value |
|---|---|
| Type | Counter |
| Description | Total LLM tokens (input + output) consumed by the express-path agent step |
| Labels | trigger, complexity, outcome |
| Source | `create-implementation` skill outcome YAML (`token_input`, `token_output`) |

### express_classification_count

| Field | Value |
|---|---|
| Type | Counter |
| Description | Count of issues classified by the triage-issue skill |
| Labels | verdict (`feature`, `bug`, `needs-info`, `other`), complexity (`low`, `medium`, `high`, `absent`), route (`express`, `full_pipeline`) |
| Source | Triage-issue skill outcome YAML |

### express_override_count

| Field | Value |
|---|---|
| Type | Counter |
| Description | Count of human-applied `llmaw:quick-implement` overrides |
| Labels | issue_labels_present (comma-separated string of existing labels) |
| Source | GitHub `issues:labeled` event payload |

### express_label_removal_count

| Field | Value |
|---|---|
| Type | Counter |
| Description | Count of express-path labels removed by humans, triggering fallback |
| Labels | label_removed, remaining_label_count |
| Source | GitHub `issues:labeled` event with `action: removed` |

### express_active_eligible_issues

| Field | Value |
|---|---|
| Type | Gauge |
| Description | Number of issues currently labeled `llmaw:express-eligible` (awaiting implementation) |
| Labels | — |
| Source | `gh issue list --label llmaw:express-eligible --json number --jq length` |

## Tracing

| Span Name | Service | Attributes | Parent Span |
|---|---|---|---|
| express_flow | GitHub Actions | issue_number, event_type, rule_name | root |
| triage_classification | GitHub Actions | issue_number, verdict, complexity, reason | express_flow |
| label_application | GitHub Actions | issue_number, label, actor | triage_classification |
| implementation_run | GitHub Actions | issue_number, trigger, complexity, timeout_minutes | express_flow |
| pr_creation | GitHub Actions | issue_number, pr_number, branch | implementation_run |
| outcome_handling | GitHub Actions | issue_number, outcome, label_set | implementation_run |

Note: GitHub Actions does not emit OpenTelemetry-compatible distributed traces. The "spans" above represent logical stages in the event-processing pipeline. Traceability is achieved through:
- `correlation_id`: the issue number links every stage of a single express-path run
- GitHub's audit log records every label transition with actor and timestamp
- The `express-decision.md` artifact records the full outcome for each issue

## Health Checks

| Check | Type | Endpoint / Method | Healthy Condition |
|---|---|---|---|
| Express flow configuration loaded | Liveness | `flows.yml` parse check on workflow start | All express rules parse without YAML errors |
| Triage skill outputs complexity | Readiness | Verify triage-issue outcome YAML contains `complexity` field when applicable | Outcome YAML validates against schema |
| Label application succeeds | Readiness | Dry-run `gh issue edit --add-label` on a test issue | Exit code 0 |
| `create-implementation` does not crash | Liveness | Agent step exits with code 0 or emits `verdict: approved|failed` (not crash) | Outcome YAML is written |

No new HTTP endpoints or services are introduced. Health checks are embedded as pre-flight validation steps in the workflow.

## Alerts

### Express Implementation Failure Rate Exceeds Threshold

| Field | Value |
|---|---|
| Condition | `express_implementation_failure_rate > 0.20` over any 7-day rolling window (computed as `express_flow_match_total{outcome="failed"}` / `express_flow_match_total` where `rule_name` matches express rules) |
| Severity | Critical |
| For | N/A (post-hoc, computed after the window closes) |
| Runbook | 1. Inspect `llmaw:express-failed` labeled issues for common failure patterns. 2. Review failure reasons in the `express-decision.md` artifacts. 3. If `create-implementation` skill crashes, check LLM API availability and token limits. 4. If classification errors, tune triage prompt or adjust eligibility criteria in `defaults.express.eligibility`. 5. Post findings to the tracking issue. |
| Notification | Slack: #engineering channel, weekly summary |

### Token Efficiency Below Target

| Field | Value |
|---|---|
| Condition | 3 consecutive express runs consume > 60% of the comparable full-pipeline token baseline |
| Severity | Warning |
| For | N/A (post-hoc) |
| Runbook | 1. Review the token consumption per run from `express_token_consumption_total`. 2. Compare against the established baseline from 5 validation runs. 3. If the express path is processing issues that are not truly low-complexity, tighten `defaults.express.eligibility.complexity_values` or `max_issue_body_chars`. 4. If the `create-implementation` skill itself is token-heavy, consider optimization. |
| Notification | Slack: #engineering channel, weekly summary |

### Classification Comment Spam

| Field | Value |
|---|---|
| Condition | More than 5 classification comments on a single issue (indicates re-classification loop) |
| Severity | Warning |
| For | N/A (post-hoc) |
| Runbook | 1. Investigate the issue's label transition history. 2. If a loop is confirmed, disable `comment_on_classification` in `defaults.express`. 3. Check whether the triage skill is being re-invoked by unintended label events. 4. If the issue has `llmaw:express-eligible` and `llmaw:express-failed` alternating, verify the flow rules prevent re-entry. |
| Notification | GitHub issue comment on the affected issue |

### Express Path Silently Degraded

| Field | Value |
|---|---|
| Condition | No `express_flow_match_total` increment for a rolling 7-day period when at least one `llmaw:express-eligible` issue exists (or new issues were created) |
| Severity | Warning |
| For | 7 days |
| Runbook | 1. Check GitHub Actions workflow run history for the dispatch workflow. 2. Verify `flows.yml` was not accidentally modified. 3. Check whether the triage skill is still emitting `complexity` correctly. 4. Manually trigger a test: create a test issue with `llmaw:quick-implement` and verify end-to-end delivery. |
| Notification | Slack: #engineering channel |

## SLOs

| SLO | Target | SLI | Measurement Window |
|---|---|---|---|
| Express implementation success rate | >= 80% | `llmaw:express-done` / (`llmaw:express-done` + `llmaw:express-failed`) | Rolling 30 days |
| Token efficiency | <= 60% of full pipeline tokens | Mean express-path token count / mean full-pipeline token count for comparable features | Per run, reviewed after 5 runs |
| Time from issue open to PR creation (express) | < 30 minutes median | Timediff between issue `created_at` and PR `created_at` for `llmaw:express-done` issues | Rolling 30 days |
| Classification false-positive rate | < 20% | Issues labeled `llmaw:express-eligible` that resolve to `llmaw:express-failed` | Rolling 30 days |

## Infrastructure Requirements

| Requirement | Type | Notes |
|---|---|---|
| Emit structured log lines from `flows.yml` on_outcome handlers | Log | Use `echo "TELEMETRY_EVENT:{\"event\":\"...\",\"properties\":{...}}" >> $GITHUB_STEP_SUMMARY` for each on_outcome transition |
| Expose `token_input`, `token_output`, `duration_seconds` in `create-implementation` outcome YAML | Metric | Required for token efficiency SLO and duration histograms |
| Collect TELEMETRY_EVENT lines across workflow runs | Log | A scheduled workflow or post-processing step should aggregate structured logs from GITHUB_STEP_SUMMARY into `.sdlc/express-telemetry.json` |
| Apply `llmaw:express-done` and `llmaw:express-failed` labels atomically | Alert | Labels are the source of truth for state queries; failed label application = lost state |
| Periodic dry-run test of the express path | Alert | A scheduled workflow should verify the express path is operational by creating a test issue, running the flow, and cleaning up |

## Out of Scope

- HTTP-level metrics (request rate, error rate, latency) — no HTTP services introduced
- Infrastructure-level metrics (CPU, memory, disk, network) — feature runs in GitHub-managed runners
- Third-party monitoring integration (Datadog, Grafana, PagerDuty) — GitHub-native tooling only
- Real-time alerting — alerts are post-hoc (daily/weekly) until express path volume exceeds 50 runs per month
- On-call rotation — no on-call response expected; alerts surface in Slack weekly summaries
