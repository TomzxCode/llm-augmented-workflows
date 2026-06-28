---
artifact: telemetry.md
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Actionability

**Two counter metrics lack investigation triggers.**
The counter metrics for "classification comment spam" (>5 comments per issue) and "manual override rate" (>50% of runs from `llmaw:quick-implement`) define thresholds but specify no alert or investigation action. The Dashboards and Alerts section only defines alert conditions for failure rate and token savings. Without triggers, these counter metrics serve as passive observations rather than actionable signals.

## Coverage Gaps

**Event emission mechanism for `on_outcome` events is underspecified.**
Events such as `classification_comment_posted`, `routing_decision_made`, `express_override_used`, and `express_label_removed` fire from `flows.yml` `on_outcome` handlers (deterministic shell/labels steps). The plan does not specify how these steps produce structured telemetry data — whether via structured log lines, writing to a telemetry YAML file, posting to the issue as structured data, or using `gh` API calls. The other events (`issue_classified`, `implementation_completed`, `implementation_failed`) source from skill outcome YAML, which is well-defined. The `on_outcome` events need a comparable emission mechanism specified.
