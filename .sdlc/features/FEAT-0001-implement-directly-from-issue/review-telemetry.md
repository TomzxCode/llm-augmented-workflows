---
artifact: telemetry.md
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Completeness

**`issue_opened` event referenced but not defined.**
The user funnel (step 1) lists `issue_opened` as an event, but no corresponding definition exists in the Analytics Events section with typed properties. If this is a GitHub-native event (`issues:opened`), clarify this in the funnel or note it explicitly. If it is intended to be a custom-analytics event, add a definition with properties.

## Measurability

No issues found.

## Actionability

No issues found.

## Consistency

**`express_eligibility_set` event name mismatches its scope.**
The event fires for both express-eligible (`llmaw:express-eligible`) and ineligible (`llmaw:feature-request`) outcomes, but the name `express_eligibility_set` implies only the eligible path. Either rename to something like `routing_decision_made` or note in the event description that it captures both outcomes.

**`full_pipeline_triggered` overlaps with `express_eligibility_set`.**
When an issue is ineligible, both `full_pipeline_triggered` and `express_eligibility_set` (with `label_applied: llmaw:feature-request`) fire from the same transition. This creates a risk of double-counting. Clarify whether both events are expected to fire simultaneously or whether one should be derived from the other.

## Coverage Gaps

**`workflow_step_failed` step_name overlaps with `implementation_failed`.**
The `workflow_step_failed` event lists `create-implementation` as a valid `step_name`, but the `implementation_failed` event already covers failures in the create-implementation step. Clarify which failure mode belongs to which event (e.g., `workflow_step_failed` covers infrastructure failures like crashes/timeouts, while `implementation_failed` covers the skill returning `verdict: failed`). Alternatively, remove `create-implementation` from `workflow_step_failed.step_name` values.
