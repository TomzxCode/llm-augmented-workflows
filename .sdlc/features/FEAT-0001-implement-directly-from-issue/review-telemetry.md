---
artifact: telemetry.md
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Completeness

No issues found.

## Measurability

**`implementation_started` event emission mechanism is underspecified.**
The trigger is "`create-implementation` agent step begins execution" but no mechanism is defined for emitting this event at the start of execution. The existing mechanisms (outcome YAML for agent skills, `$GITHUB_STEP_SUMMARY` for `on_outcome` handler events) do not cover mid-step emission. The plan should specify how the workflow emits this event before the agent step runs (e.g., via `echo "TELEMETRY_EVENT:{...}"` in a shell step that runs immediately before the agent invocation).

## Actionability

No issues found. The two counter metrics previously lacking investigation triggers now have alert actions defined in the Dashboards and Alerts section.

## Consistency

**`previous_labels` property has inconsistent semantics across events.**
For `express_override_used`, `previous_labels` is described as "Labels on the issue before the override." For `express_label_removed`, the same property name is described as "Labels remaining on the issue after removal." The same property name should have the same meaning. Either rename the `express_label_removed` property to `remaining_labels` (or `current_labels`) to match its description, or change its description to match the "before event" semantics used by `express_override_used`.

## Coverage Gaps

**`workflow_step_failed` event has no concrete emission mechanism.**
The location is described as "GitHub Actions workflow run logs; inferred from step failure in the workflow" but no inference or collection pipeline is specified. The telemetry requirements do not include a log-processing step that would scan workflow run logs for failures. Without a concrete mechanism, this event cannot be reliably emitted. Either specify how failures are collected (e.g., a post-processing step that reads the workflow run API, or a `failure()` handler in `flows.yml` that emits structured log lines to `$GITHUB_STEP_SUMMARY`) or document this event as deferred to a future version.
