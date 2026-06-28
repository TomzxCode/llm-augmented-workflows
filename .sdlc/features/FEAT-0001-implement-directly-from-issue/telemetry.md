---
issue: "#17"
title: "Implement directly from issue"
status: in-review
revision: 2
---

# Telemetry: Implement directly from issue

## Overview

This feature adds an express path that routes eligible issues directly from triage to implementation, skipping intermediate planning phases. Telemetry measures express path adoption, implementation success rate, token efficiency relative to the full pipeline, and classification accuracy. Because this is a GitHub Actions workflow, instrumentation is label-based — GitHub itself serves as the event store via label transitions and issue comments.

## Success Metrics

| Metric | Target | Measurement Method | Timeframe |
|---|---|---|---|
| Express-path adoption rate | > 30% of feature-classified issues | `gh issue list --label llmaw:express-done` / `gh issue list --label llmaw:feature-request` | Monthly |
| Express implementation success rate | > 80% | `gh issue list --label llmaw:express-done` / (`llmaw:express-done` + `llmaw:express-failed`) | Monthly |
| Classification breakdown visibility | Eligible vs. ineligible counts tracked | Aggregate `issue_classified` events by verdict and complexity; report as label-based queries (`llmaw:express-eligible` vs. `llmaw:feature-request`) | Monthly |
| Token savings vs. full pipeline | < 60% of full pipeline tokens | Compare express-run token counts against a historical baseline of 5 comparable full-pipeline runs (established during validation). In production, report absolute token counts per run without a counterfactual; the baseline is re-evaluated quarterly. Two-tailed t-test (p < 0.05) used during baseline establishment. | Per run, reviewed after 5 runs |
| Median time from issue open to PR creation | < 30 min for express path | Timediff between `created_at` and PR `created_at` for issues with `llmaw:express-done` | Weekly |
| Classification accuracy | < 20% false-positive rate | Issues labeled `llmaw:express-eligible` that resolve to `llmaw:express-failed` | Per run |

## User Funnel

| Step | Event | Entry Criteria | Exit Criteria |
|---|---|---|---|
| 1. Issue filed | `issues:opened` (GitHub native webhook event, not a custom analytics event) | Issue is created in the repository | Triage workflow fires |
| 2. Issue classified | `issue_classified` | Triage-issue skill runs | Verdict + complexity emitted to outcome YAML |
| 3. Routing decision made | `routing_decision_made` | Triage verdict + complexity emitted | Label `llmaw:express-eligible` (express path) or `llmaw:feature-request` (full pipeline) applied |
| 4. Implementation started | `implementation_started` | `create-implementation` agent step invoked | Agent produces code changes or errors |
| 5. PR created (success) | `implementation_completed` | `create-implementation` succeeds | PR posted + `llmaw:express-done` label set |
| 5a. Implementation failed | `implementation_failed` | `create-implementation` encounters error | `llmaw:express-failed` label set + error comment posted |

**Manual override funnel (alternate entry):**

| Step | Event | Entry Criteria | Exit Criteria |
|---|---|---|---|
| 1. Human applies label | `express_override_used` | Human adds `llmaw:quick-implement` to any issue | Express flow matches on next `issues:labeled` event |
| 2. Implementation started | `implementation_started` | `create-implementation` agent step invoked | Same success/failure paths as above |

## Analytics Events

### issue_classified

**Trigger:** Triage-issue skill writes its verdict to outcome YAML
**Location:** `triage-issue` skill output in `.sdlc/artifacts/` or `$OUTCOME_YAML`

| Property | Type | Required | Description |
|---|---|---|---|
| issue_number | number | Yes | GitHub issue number |
| verdict | string | Yes | `feature`, `bug`, `needs-info`, `other` |
| complexity | string | No | `low`, `medium`, `high`; absent when not determined |
| reason | string | No | Free-text rationale for classification |
| source | string | Yes | `server` |

### classification_comment_posted

**Trigger:** Triage flow `on_outcome` posts classification rationale as an issue comment (controlled by `defaults.express.comment_on_classification`)
**Location:** `flows.yml` on_outcome handler

| Property | Type | Required | Description |
|---|---|---|---|
| issue_number | number | Yes | GitHub issue number |
| verdict | string | Yes | `feature`, `bug`, `needs-info`, `other` |
| complexity | string | No | `low`, `medium`, `high`; absent when not determined |
| route | string | Yes | `express` or `full_pipeline` |
| source | string | Yes | `server` |

### routing_decision_made

**Trigger:** Triage flow `on_outcome` applies `llmaw:express-eligible` or `llmaw:feature-request` label
**Location:** `flows.yml` on_outcome handler (deterministic shell/labels step)

| Property | Type | Required | Description |
|---|---|---|---|---|
| issue_number | number | Yes | GitHub issue number |
| label_applied | string | Yes | `llmaw:express-eligible` or `llmaw:feature-request`; when `llmaw:feature-request`, indicates full pipeline routing |
| complexity | string | No | Emitted complexity from classification |
| routing_reason | string | No | Why the issue was routed to full pipeline (e.g., `complexity_high`, `exclusion_label`, `body_too_long`); present only when `label_applied` is `llmaw:feature-request` |
| source | string | Yes | `server` |

### implementation_started

**Trigger:** `create-implementation` agent step begins execution
**Location:** GitHub Actions workflow logs for the express flow rule

| Property | Type | Required | Description |
|---|---|---|---|
| issue_number | number | Yes | GitHub issue number |
| trigger | string | Yes | `classification` or `manual` |
| complexity | string | No | Complexity verdict from triage |
| issue_body_length | number | Yes | Character count of the issue body |
| source | string | Yes | `server` |

### implementation_completed

**Trigger:** `create-implementation` succeeds and creates a PR
**Location:** `create-implementation` skill outcome YAML

| Property | Type | Required | Description |
|---|---|---|---|
| issue_number | number | Yes | GitHub issue number |
| pr_number | number | Yes | Pull request number created |
| trigger | string | Yes | `classification` or `manual` |
| complexity | string | No | Complexity verdict from triage |
| token_input | number | Yes | LLM input tokens consumed |
| token_output | number | Yes | LLM output tokens consumed |
| duration_seconds | number | Yes | Wall-clock time for the agent step |
| source | string | Yes | `server` |

### implementation_failed

**Trigger:** `create-implementation` fails or returns `verdict: failed`
**Location:** `create-implementation` skill outcome YAML

| Property | Type | Required | Description |
|---|---|---|---|
| issue_number | number | Yes | GitHub issue number |
| trigger | string | Yes | `classification` or `manual` |
| complexity | string | No | Complexity verdict from triage |
| failure_reason | string | Yes | Free-text description of the failure |
| token_input | number | Yes | LLM input tokens consumed before failure |
| token_output | number | Yes | LLM output tokens consumed before failure |
| duration_seconds | number | Yes | Wall-clock time before failure |
| source | string | Yes | `server` |

### workflow_step_failed

**Trigger:** An upstream infrastructure step fails (triage skill crash, label application failure via `gh issue edit`, workflow dispatch error, or missing outcome YAML)
**Location:** GitHub Actions workflow run logs; inferred from step failure in the workflow

| Property | Type | Required | Description |
|---|---|---|---|
| issue_number | number | No | GitHub issue number if available at the failure point |
| step_name | string | Yes | `triage-issue`, `apply-label`, `dispatch-express` (NOT `create-implementation`; use `implementation_failed` for that step) |
| error_type | string | Yes | `skill_crash`, `label_apply_failed`, `workflow_dispatch_error`, `missing_outcome`, `timeout` |
| error_message | string | No | Free-text error detail from workflow logs |
| source | string | Yes | `server` |

**Note:** `workflow_step_failed` covers infrastructure failures (skill crash, label apply failure, workflow dispatch error, missing outcome YAML, timeout). For the `create-implementation` step specifically, use the `implementation_failed` event which captures domain-level failures (skill returning `verdict: failed`) with token and duration properties.

### express_override_used

**Trigger:** Human applies `llmaw:quick-implement` label to an issue
**Location:** GitHub issue label event (inferable from `issues:labeled` payload)

| Property | Type | Required | Description |
|---|---|---|---|
| issue_number | number | Yes | GitHub issue number |
| previous_labels | string[] | Yes | Labels on the issue before the override |
| source | string | Yes | `server` |

### express_label_removed

**Trigger:** A human removes `llmaw:express-eligible` or `llmaw:quick-implement` from an issue, causing fallback to the full pipeline
**Location:** GitHub issue label event (inferable from `issues:labeled` event payload with `action: removed`)

| Property | Type | Required | Description |
|---|---|---|---|
| issue_number | number | Yes | GitHub issue number |
| label_removed | string | Yes | `llmaw:express-eligible` or `llmaw:quick-implement` |
| previous_labels | string[] | Yes | Labels remaining on the issue after removal |
| source | string | Yes | `server` |

## Counter Metrics

| Metric | Concern | Threshold |
|---|---|---|
| Express implementation failure rate | Express path produces too many failures, eroding trust | > 20% of express-path runs end in `llmaw:express-failed` |
| Classification false-positive rate | Triage over-classifies issues as low-complexity when they are not | > 20% of `llmaw:express-eligible` issues resolve to `llmaw:express-failed` |
| Token savings below target | Express path does not deliver promised efficiency gains | 3 consecutive express runs consuming > 60% of comparable full-pipeline tokens |
| Classification comment spam | `comment_on_classification` generates excessive noise on issues | > 5 classification comments per issue (indicates re-classification loop) |
| Manual override rate | Users feel the need to bypass classification regularly | > 50% of express-path runs originate from `llmaw:quick-implement` (not auto-classification) |

## Telemetry Requirements

| Requirement | Type | Notes |
|---|---|---|
| Emit `triage-issue` verdict + complexity to outcome YAML | Infrastructure | Already implemented in the triage skill extension; provides input for all downstream events |
| Read `create-implementation` outcome YAML for token counts and duration | Infrastructure | The `create-implementation` skill must emit `token_input`, `token_output`, and `duration_seconds` in its outcome |
| Log express path usage as label queries | Dashboard | Query `llmaw:express-done`, `llmaw:express-failed`, `llmaw:express-eligible` labels for ad-hoc metrics |
| Record LLM token usage per run | Event | Token counts must be read from LLM API call metadata in the agent step |
| Compute time-to-PR per express run | Dashboard | Difference between issue `created_at` and PR `created_at` for `llmaw:express-done` issues |

## Dashboards and Alerts

- **Dashboard:** GitHub issue search queries (labels). No external dashboard initially. Key queries:
  - `is:issue is:closed label:llmaw:express-done` — all successfully implemented express features
  - `is:issue label:llmaw:express-failed` — all failed express attempts
  - `is:issue label:llmaw:express-eligible` — issues awaiting express implementation
  - `is:issue label:llmaw:quick-implement` — manual override usage
- **Alerts:** If express-path failure rate exceeds 20% in any 7-day window, post a summary comment to the tracking issue. If token savings fall below target for 3 consecutive runs, flag the classification criteria for review.

## Out of Scope

- **External analytics service integration** (e.g., PostHog, Amplitude, Google Analytics). The label-based approach is sufficient for the expected volume and avoids new dependencies per project constraints.
- **Per-user or per-contributor tracking.** Only aggregate metrics are collected to preserve contributor privacy.
- **Real-time dashboards.** Metrics are reviewed on a weekly/monthly cadence via GitHub search.
- **Automated alerting.** Alerts are manual (periodic review) until express path volume exceeds 50 runs per month.
- **Conversion tracking across the full SDLC pipeline.** Only the express path is instrumented; the full pipeline retains its existing metrics.
