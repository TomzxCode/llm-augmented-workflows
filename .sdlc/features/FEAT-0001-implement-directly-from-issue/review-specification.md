---
artifact: specification.md
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Ambiguities

**What "configurable criteria" means concretely.** The spec references a `defaults.express` block in `flows.yml` but does not define its fields (e.g., which complexity values qualify, whether issue label or body heuristics are used). The requirements define FR-01 as "configurable criteria" but the spec defers the actual schema to an unspecified config block.

**`express-decision.md` schema does not record the classification's "why."** FR-03 requires "an artifact recording that the express path was used and why." The schema has `trigger`, `complexity`, and `outcome`, but no `reason` field capturing the triage rationale. The "why" is only partially derivable from the combination of fields.

**Who runs `create-pr`?** The sequence diagram shows `on_outcome: approved` creating a PR "via create-pr skill," but the express flow's `on_outcome` only defines label transitions. It is unclear whether the flow engine itself invokes `create-pr` or whether `create-implementation` is responsible for triggering the PR creation.

## Inconsistencies

**Artifact trail vs. "no planning artifacts."** FR-02's acceptance criterion states "no requirements, existing-solutions, ... plan artifacts exist for this feature," yet the spec introduces `express-decision.md` under `.sdlc/features/`. The intent is clearly "no planning-phase artifacts," but the wording in the requirement could cause conflict with the new artifact. Minor, but worth aligning.

**Label state machine shows `create-implementation` then `on_outcome`, but `on_outcome.approved` relies on `create-pr`.** The express flow's `on_outcome` table shows `approved` → "Set llmaw:express-done, create PR." If `create-pr` is a separate skill, who calls it? The sequence diagrams hand-wave this as "creates PR via create-pr skill" outside the flow engine's `on_outcome` semantics.

## Incoherences

**`create-implementation` depends on upstream artifacts it won't have.** The risks section correctly identifies that `create-implementation` may depend on requirements, specifications, and codebase-analysis artifacts. Yet the spec runs it without those artifacts. This is flagged as a risk but is also a design tension: if the dependency is hard (not just a soft recommendation), the express path cannot work without changes to `create-implementation`.

## Missing Information

**NFR-05 (anti-spoofing) is entirely unaddressed.** The requirements state: "The classification logic shall reject attempts to spoof eligibility via label manipulation on issues that do not meet the configured criteria." The spec defines no guard against a human (or a compromised actor) manually applying `llmaw:express-eligible` to skip planning on a complex feature. The `llmaw:quick-implement` label is intentionally a bypass, but `llmaw:express-eligible` should be auto-only.

**FR-05 (classification logging) is partially covered.** The requirement says "log the classification decision and rationale to the issue or a corresponding artifact." The spec writes to `express-decision.md` but does not specify posting a comment on the issue. The triage skill's `$OUTCOME_YAML` carries the reason, but it is not clear whether that reason surfaces to the issue or only lives in the engine's internal state.

**FR-06 (removing label to route to full pipeline) is not specified.** The requirement's acceptance criteria cover both adding and removing the express label. The spec only covers the manual override via `llmaw:quick-implement` (add label → express). It does not address the inverse: an eligible issue whose express label is removed should fall back to the full pipeline on the next cycle.

**No performance targets or SLAs.** NFR-01 requires the express path to "complete in fewer total tokens than the full pipeline" but no concrete target, baseline measurement, or verification method is defined.

**No LLM provider or model configuration for `defaults.express`.** The spec mentions a `defaults.express` config block but does not specify its fields (model selection, token budget, timeout, retry policy).

## Implementability

**`create-implementation` must work without planning artifacts.** This is the central implementability risk. The spec treats `create-implementation` as a black box that "produces implementation + tests" from "issue body + labels only." If the current `create-implementation` skill requires requirements or specification artifacts to function (reading them as context), the express path will fail on every run until `create-implementation` is modified to work from issue content alone. The spec says this is "tested as-is, modified separately if needed" but that makes the entire feature contingent on a change in another component without defining the interface.

**Cross-repo coordination is not specified in detail.** The `triage-issue` skill lives in `tomzx/agents` while the express flow lives in this repository. The spec notes this as a risk but does not define the deployment ordering, version compatibility strategy, or how the consuming flow detects that the triage skill has been updated to emit the `complexity` field.

**No explicit interface contract for the `defaults.express` config block.** The spec references it but does not define its shape. Without a schema, the implementation cannot be validated against the configuration.

## Reversibility

**Terminal labels (`llmaw:express-done`, `llmaw:express-failed`) are irreversible within the flow engine.** The spec labels them "Terminal." Once set, the flow engine will not re-process the issue through any path (express or full). A human would need to manually remove the label to re-trigger processing. This is a one-way-door decision for each issue. This should be called out explicitly as a design commitment.

**No cleanup of `express-decision.md` if an express-path feature is later re-processed through the full pipeline.** If an issue gets `llmaw:express-failed` and a human later removes it and triggers the full pipeline, the old `express-decision.md` artifact persists with a `failed` outcome. This could cause confusion for future readers.

## Forward Compatibility

**The spec does well on forward compatibility for `flows.yml` rules and verdict schemas** (unknown fields, new labels, default `_` handler for verdicts). These are explicitly documented.

**`express-decision.md` artifact schema is not versioned.** If the schema evolves (e.g., adding `duration_seconds`, `model_used`), consumers reading old artifacts have no indicator of which schema version to expect.

**Enum growth for `complexity` values is not addressed.** The spec says `low | medium | high`, and treats absent as "not eligible." If a new value like `trivial` or `very-high` is added later, consumers must not crash. The spec does not document this tolerance.

**`triage-issue` verdict YAML is documented as extensible** (consumers MUST ignore unknown fields). Good.
