---
artifact: specification.md
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Ambiguities

No issues found.

The previous finding about anti-spoofing verification being underspecified has been resolved. The spec now commits to a concrete three-layer approach (label compartmentalization, audit trail via issue timeline, failure-driven damage limitation) with zero engine changes.

## Inconsistencies

**Line 163 describes an `issues:opened` match scenario that the defined rules cannot satisfy.** The spec states: "If an issue is created with `llmaw:quick-implement` pre-applied (e.g., via API), the `issues:opened` event carries the label in its payload and the express rule matches on that single event." However, both express rules define `when.event: issues:labeled` (lines 145, 155), and the Technical Decisions entry (line 388) confirms "`issues:opened` trigger: Not used; `issues:labeled` is the sole trigger." A rule matching `issues:labeled` will never fire on an `issues:opened` event regardless of which labels the payload carries. The API pre-labeled scenario would not trigger the express flow under the current rule schemas. Either add `issues:opened` as an additional event match on the `express-quick-implement` rule, or correct the descriptive text to clarify that the label must be applied post-creation to fire `issues:labeled`.

The following previous findings have been resolved and verified in revision 1:
- `when.labels` (plural, array) vs. `when.label` (singular, string): Resolved. The spec now defines two separate rules, each matching a single label, consistent with the engine's `When` dataclass.
- `issues:opened` listed as a trigger: Resolved. The rules now use only `issues:labeled`. (The new inconsistency above is a separate issue in the descriptive text.)
- `defaults.express` config keys not consumed: Resolved. The spec now specifies which component consumes each key (triage `on_outcome` for eligibility config, `dispatch.yml` for model/timeout) and that all are read by deterministic steps, not `engine.py`.

## Incoherences

No issues found.

The previous finding about anti-spoofing (NFR-05) contradicting the "zero engine changes" claim has been resolved. The label-compartmentalization design (two distinct label strings) operates entirely within the engine's existing `matches()` capability. The previous finding about `create-implementation` dependency on planning artifacts has been resolved with a dedicated "Minimum Interface Contract" section specifying inputs, behavioral contract, and token scope requirements.

## Missing Information

No issues found.

The previous findings about NFR-01 and NFR-02 have been resolved. NFR-01 now has a concrete target (at most 60% of the full pipeline's token count) with a measurement method and statistical significance criterion (two-tailed t-test, p < 0.05). NFR-02 now has a verification plan (CI checks + manual quality comparison of 3 historical-issue PRs).

## Implementability

No issues found.

The previous findings (two rules instead of one, GitHub token scopes for PR creation) have been resolved. The spec now defines two explicit rules matching the engine's singular `label` field, and documents the required `contents: write` and `pull-requests: write` token scopes. The `create-implementation` contract is sufficiently specified to implement against.

## Reversibility

No issues found. Terminal labels, artifact persistence, and retry semantics remain explicitly documented as design commitments.

## Forward Compatibility

No issues found. The spec maintains strong forward-compatibility practices: `schema_version` on the decision artifact, unknown-field tolerance on all YAML schemas, extensibility notes for enum growth and new config keys, and a default-case catch for unhandled verdict values.
