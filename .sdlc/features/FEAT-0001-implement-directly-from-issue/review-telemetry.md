---
artifact: telemetry.md
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Completeness

**Classification comment posting (FR-05) not instrumented.**
The specification defines a `comment_on_classification` config (default `true`) that posts the classification rationale as an issue comment. The telemetry has a counter metric for "Classification comment spam" but no event tracks when a classification comment is actually posted. Without an event, the counter metric cannot be computed. Add a `classification_comment_posted` event or clarify how the comment count is derived (e.g., from GitHub issue comments API).

**Label-removal fallback flow not instrumented.**
The specification describes a flow where a human removes `llmaw:express-eligible` and the issue falls back to the full pipeline. This path has no corresponding event. While this is an edge case, instrumenting it would close a coverage gap. Add an `express_label_removed` event or document why this path is intentionally excluded.

**FR-07 classification breakdown metric missing.**
The requirement asks for "a breakdown of classifications" (eligible vs. ineligible counts). The adoption rate captures express-path share but not the full classification distribution. Add a success metric for classification breakdown or clarify how the `issue_classified` event data is aggregated.

## Measurability

**Token savings comparison methodology unclear.**
The metric compares an express run against "comparable full-pipeline run" using a t-test. The spec validates against historical issues, but during ongoing operation there is no counterfactual full-pipeline run for the same issue. Clarify whether the comparison uses a historical baseline, synthetic benchmarks, or is omitted in production and computed only during testing.

No other measurability issues found. All metrics have concrete targets, measurement methods, and timeframes.

## Actionability

No issues found. Counter metrics have clear thresholds and investigation triggers. Alert descriptions specify both the condition and the response action. The manual-review approach is appropriate for the expected volume.

## Consistency

No issues found. Event names follow `snake_case` and `entity_action_status` convention. Properties are typed with required/optional marked. Terminology (complexity, trigger, verdict) matches the specification.

## Coverage Gaps

**Triage and infrastructure failures not instrumented.**
The telemetry covers implementation failures but not failures in upstream steps: triage-skill crashes (no outcome YAML emitted), label application failures (`gh issue edit` fails), or workflow dispatch errors. While these may be caught by GitHub Actions run logs, they are invisible to the label-based query system. Add events or document that these are monitored via GitHub Actions workflow run logs.

No other coverage gaps found. The label-based infrastructure is sufficient for defined events. Dashboards and alert criteria are specified.
