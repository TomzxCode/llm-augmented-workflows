---
artifact: specification.md
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Ambiguities

**Anti-spoofing verification mechanism is underspecified.** The spec says the flow rule "MUST check that the label was applied by the automation (e.g., by verifying the issue timeline or requiring that `llmaw:express-eligible` was set in the same workflow run)." The "e.g." lists two approaches but does not commit to one. The existing flow engine (`engine.py:matches()`) has no concept of label origin — it matches solely on label name. Whichever approach is chosen will require either engine changes or a different architectural pattern. The spec should specify which approach is used.

## Inconsistencies

**`when.labels` (plural, array) does not match the engine's `when.label` (singular, string).** The spec's flow rule table defines `when.labels` as an array of two labels (`llmaw:express-eligible`, `llmaw:quick-implement`). The engine's `When` dataclass (`engine.py:30-36`) uses `label: str | None` (singular string), and `parse_when()` reads `raw.get("label")`. The `matches()` function compares `when.label` against the single label in the event payload (`payload.get("label", {}).get("name")`). The express rule cannot match two different labels in a single rule given the current engine schema. The spec must either define separate rules per trigger label or modify the engine to support `when.labels` (array).

**`issues:opened` is listed as a trigger but cannot match the express flow under normal conditions.** The express flow rule lists `when.event: issues:opened` alongside `issues:labeled`. On `issues:opened`, there is no label in the event payload (the triage flow runs first and sets the label on a separate `issues:labeled` event). The engine's `matches()` compares `when.label` against `payload.label.name`, which is absent on `issues:opened`, so the rule would never match. Only `issues:labeled` is a valid trigger for the express flow. Either remove `issues:opened` or document the pre-condition under which it would match (e.g., issue created with `llmaw:quick-implement` pre-applied via API).

**`defaults.express` config keys are referenced but not consumed by any engine code.** The spec defines a `defaults.express` block in `flows.yml` with fields like `eligibility.complexity_values`, `max_issue_body_chars`, etc. The engine reads `defaults` only for `model`, `agents_repository`, and `timeout_minutes` (`engine.py:189, 168-172`). None of the express-specific config keys are read by any current engine code. The spec does not specify which component reads this config or how it flows to the triage classification step. This is a gap between the config schema and the consuming logic.

## Incoherences

**Anti-spoofing (NFR-05) contradicts the "zero engine changes" claim.** The spec states in Technical Decisions: "Flow model: New express flow in `flows.yml` — Mirrors the existing bugfix pattern; requires zero engine changes; orthogonal to existing flows." However, the Anti-spoofing section (line 90) says the flow rule "MUST check that the label was applied by the automation" and "MUST verify that the triage verdict exists and matches before routing." The engine's `matches()` function (`engine.py:233-258`) has no capability to verify label origin or cross-reference the triage verdict. Implementing NFR-05 requires either: (a) modifying the engine to add origin verification, (b) moving the check into the rule's deterministic steps, or (c) using a different label (not `llmaw:express-eligible`) as the trigger. The spec must reconcile this tension: either acknowledge that engine changes are required or specify a mechanism that uses existing engine capabilities.

**`create-implementation` dependency on planning artifacts remains unresolved.** The spec acknowledges this as a risk but lists it as "Out of Scope" (line 357). The entire express path hinges on `create-implementation` functioning from "issue body + labels only." If the skill hard-depends on requirements or specification artifacts (e.g., imports them as context), the express path cannot ship without modifying `create-implementation`. The spec should either specify the minimal interface contract that `create-implementation` must satisfy (making the dependency explicit) or commit to modifying it.

## Missing Information

**NFR-01 (token savings) has no concrete target or measurement method.** The text in Risks (line 351) suggests "A 40%+ reduction is a reasonable initial target" but this is not a spec-level commitment. The spec must define a measurable success criterion (e.g., "express path consumes at most 60% of the full pipeline's token count for comparable features") and how it will be measured.

**NFR-02 (code quality) is not addressed.** The requirements state: "The express path shall not reduce code quality below the standard of the full pipeline; implementations must still pass normal CI checks." The spec does not define what "standard of the full pipeline" means or how code quality is verified beyond CI checks (which the full pipeline also passes). If the full pipeline produces more robust code through its planning phases (spec-driven, reviewed), the spec should acknowledge the quality delta risk and define compensating measures or an acceptance threshold.

## Implementability

**Express flow needs two rules, not one.** Because the engine's `when.label` matches a single label name, the express flow must define two separate rules in `flows.yml`:
1. `express-implement-from-eligible` — matches `issues:labeled` + `label: llmaw:express-eligible`
2. `express-quick-implement` — matches `issues:labeled` + `label: llmaw:quick-implement`

Alternatively, the engine must be extended to support `when.labels` (array). Either option should be specified explicitly.

**`create-implementation` agent step's PR creation depends on GitHub token scopes.** The spec delegates PR creation to the `create-implementation` agent step via internal `create-pr` or `gh`. The agent step runs in the Actions workflow token context, which may have branch creation and PR creation scopes. This is not documented in the spec. If the token lacks these scopes, the express path will silently fail at the PR-creation step.

## Reversibility

No issues found. Terminal labels, artifact persistence, and retry semantics are all explicitly documented as design commitments.

## Forward Compatibility

No issues found. The spec has strong forward-compatibility practices: `schema_version` on the decision artifact, unknown-field tolerance on all YAML schemas, and extensibility notes for enum growth and new config keys.

## Unresolved Open Questions

1. How does the express flow rule verify label origin for anti-spoofing (NFR-05) without engine changes? This contradicts the zero-engine-changes design decision and must be resolved before implementation.
2. Can `create-implementation` produce output from "issue body + labels only" without modification? The spec should verify this before shipping the express path.
3. How does `defaults.express` config flow to the triage classification logic? No engine component currently reads these keys.
