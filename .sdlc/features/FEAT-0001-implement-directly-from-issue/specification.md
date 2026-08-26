---
issue: "#17"
title: "Implement directly from issue"
status: approved
revision: 2
---

# Specification: Implement directly from issue

## Overview

The express path adds a lightweight third flow to the existing label-driven state machine (`flows.yml`) that routes eligible issues directly from triage to implementation, skipping all intermediate planning phases. The only planning-phase artifacts that are NOT produced are: requirements, existing-solutions, codebase-analysis, feasibility, specifications, telemetry, observability, plan, and tasks. A minimal routing record (`express-decision.md`) IS produced to satisfy traceability (FR-03). This is not a "planning artifact" — it is a routing/outcome record analogous to a CI build log. The triage-issue skill is extended to emit a `complexity` verdict field; issues classified as `feature` + `complexity: low` are labeled `llmaw:express-eligible` and matched by a new `express` flow rule that runs only `create-implementation`. A human-applied `llmaw:quick-implement` label bypasses automatic classification. The existing `feature` and `bugfix` flows are unchanged, and all engine internals (`engine.py`, `route.py`, `run_rule.py`, `run_steps.py`, `apply_outcome.py`) are reused as-is.

## Architecture

```
GitHub event (issues: opened, labeled, ...)
  |
  v
  dispatch.yml  [REUSE]
  |
  v
  route.py -> engine.py  [REUSE]
    matches rules from flows.yml against event
  |
  v
  run_rule.py -> run_steps.py + apply_outcome.py  [REUSE]
  |
  +-- [if triage flow match]  ->  triage-issue skill [EXTEND]
  |     emits verdict: feature|bug|needs-info|other
  |     emits complexity: low|medium|high  [NEW, optional]
  |
  +-- [if feature flow match]  ->  14+ create-* + review-* skills  [UNCHANGED]
  |     matched when llmaw:feature-request is set
  |
  +-- [if bugfix flow match]   ->  3-skills bugfix path  [UNCHANGED]
  |     matched when llmaw:bug is set
  |
  +-- [if express flow match]  ->  create-implementation skill  [NEW FLOW]
        matched when llmaw:express-eligible or llmaw:quick-implement is set
        produces implementation PR directly from issue description
```

### Label State Machine (Express Path)

```
                    triage-issue skill emits
                    verdict: feature + complexity: low
                            |
                            v
                    llmaw:express-eligible
                            |
                            v
                    create-implementation agent step
                            |
                            v
              +--------+--------+
              |                 |
              v                 v
        success           failure
              |                 |
              v                 v
    llmaw:express-done   llmaw:express-failed
    + PR created         + comment with error
                          + no PR
```

Human override path (FR-06):

```
                    Human applies llmaw:quick-implement label
                            |
                            v
                    create-implementation agent step
                      (skips triage entirely)
```

## Data Models

### Label Definitions

All labels added to the `llmaw:` namespace in `flows.yml`.

| Label | Type | Set by | Description |
|---|---|---|---|---|
| `llmaw:express-eligible` | Milestone (transient) | Automation only | Set automatically when triage classifies issue as feature + low complexity. Triggers the `express-implement-from-eligible` rule. |
| `llmaw:quick-implement` | Human-applied | Human | Manual override: routes any issue through the express path regardless of triage verdict. Intentionally bypasses classification. Triggers the `express-quick-implement` rule. |
| `llmaw:express-done` | Terminal | Automation | Set when express-path implementation succeeds and a PR is created |
| `llmaw:express-failed` | Terminal | Automation | Set when express-path implementation fails |

**Anti-spoofing (NFR-05):** The label trust model follows the same convention as existing flows (the engine matches labels by name, not by origin — `engine.py:matches()` matches `when.label` against `payload.label.name`). The anti-spoofing guarantee comes from three layers:

1. **Compartmentalized label names:** Two distinct labels exist for the two entry paths. `llmaw:express-eligible` is only ever set by the triage flow's `on_outcome` handler as a deterministic step (`gh issue edit --add-label`). `llmaw:quick-implement` is a separate label that a human explicitly applies. The engine does not need to distinguish origin because the two labels are different strings.

2. **Audit trail via issue timeline:** Every label application is recorded in the issue timeline with the actor (automation bot vs. human). If a human maliciously applies `llmaw:express-eligible`, it is visible in the timeline. This is the same level of audit available for any `llmaw:*` label today.

3. **Label compartmentalization prevents mistaken spoofing:** A human who applies `llmaw:express-eligible` bypasses the triage classification but still goes through the express implementation step, which must produce working code. The implementation step's failure mode (`llmaw:express-failed`) limits damage. If a human intends to bypass classification, they should use `llmaw:quick-implement` which is the documented manual override (FR-06).

This design requires zero engine changes, consistent with the decision to reuse all engine components as-is.

### Triage Verdict Schema (extended)

The `triage-issue` skill writes to `$OUTCOME_YAML`:

```yaml
verdict: feature          # existing: feature | bug | needs-info | other
complexity: low           # NEW, optional: low | medium | high
reason: "..."             # existing
```

The `complexity` field is optional. When absent, consumers treat the issue as NOT eligible for the express path. This ensures backward compatibility with older versions of the triage skill.

### Express Decision Artifact

Minimal artifact written to `.sdlc/features/FEAT-NNNN-<slug>/express-decision.md`:

```yaml
---
schema_version: 1
path: express
implemented_from: issue #<N>
trigger: classification | manual
complexity: low | medium | high
reason: "<triage classification rationale>"  # FR-03 "why"
implemented_at: <ISO datetime>
outcome: success | failed
pr_url: <url>  # present on success
---
```

**Forward compatibility:** Consumers MUST ignore unknown top-level fields. The `schema_version` field enables consumers to detect which schema generation an artifact uses. New complexity values (e.g., `trivial`, `very-high`) may be added; consumers MUST treat unrecognized values as "not express-eligible."

## API Contracts

This feature does not introduce new HTTP APIs. The contract surface is:

### flows.yml — New Express Flow

A new `express` top-level key in `flows.yml` with two rules that match on different labels. The flow follows the same rule schema as the existing `feature` and `bugfix` flows. The engine's `When` dataclass uses `label: str | None` (singular string, `engine.py:30-36`), so each rule matches exactly one label.

**Rule: `express-implement-from-eligible`** (auto-classified)

| Field | Value |
|---|---|
| `when.event` | `issues:labeled` |
| `when.label` | `llmaw:express-eligible` |
| `steps.agent` | `create-implementation` |
| `on_outcome.approved` | Set `llmaw:express-done`, post "Implementation ready at PR #&lt;N&gt;" comment |
| `on_outcome.failed` | Set `llmaw:express-failed`, comment error |

**Rule: `express-quick-implement`** (manual override)

| Field | Value |
|---|---|
| `when.event` | `issues:labeled` |
| `when.label` | `llmaw:quick-implement` |
| `steps.agent` | `create-implementation` |
| `on_outcome.approved` | Set `llmaw:express-done`, post "Implementation ready at PR #&lt;N&gt;" comment |
| `on_outcome.failed` | Set `llmaw:express-failed`, comment error |

The `create-implementation` agent step is responsible for producing the code changes AND creating the PR (by invoking the `create-pr` skill internally or using `gh` directly before it exits). The `on_outcome` handler only manages labels and comments; it does not create the PR. This keeps the PR-creation logic inside the agent step where it can access the implementation branch and commit SHA.

The `issues:labeled` event is the sole trigger for both rules. On `issues:opened`, the triage flow runs first and sets `llmaw:express-eligible` as part of its `on_outcome` deterministic steps; that label change fires a subsequent `issues:labeled` event which matches the express rule. If a human adds `llmaw:quick-implement` after creation, the label change fires `issues:labeled` and matches the express-quick-implement rule. Labels applied pre-creation are not matched because `when.event: issues:labeled` only fires on label changes, not on issue creation.

**Forward compatibility:** Consumers must ignore unknown fields in any rule schema. New rule entries may be added for additional trigger labels without breaking existing rules.

### defaults.express — Express Path Config Block

A new `defaults.express` key in `flows.yml` under the existing `defaults:` top-level block. All fields are optional; defaults shown below.

```yaml
defaults:
  express:
    eligibility:
      complexity_values: ["low"]            # complexity levels that qualify for express path
      require_labels: []                    # extra labels that must be present (e.g., "good-first-issue")
      exclude_labels: ["llmaw:complex"]     # labels that disqualify regardless of complexity
      max_issue_body_chars: 5000            # issues longer than this are not eligible
    model: ""                               # LLM model override; empty = use defaults.model
    timeout_minutes: 15                     # max wall-clock for create-implementation
    comment_on_classification: true         # whether to post classification rationale as issue comment
```

| Field | Type | Default | Description |
|---|---|---|---|
| `eligibility.complexity_values` | string[] | `["low"]` | Complexity verdict values that qualify for the express path |
| `eligibility.require_labels` | string[] | `[]` | Labels that MUST be present on the issue for express eligibility |
| `eligibility.exclude_labels` | string[] | `["llmaw:complex"]` | Labels that disqualify the issue regardless of complexity |
| `eligibility.max_issue_body_chars` | integer | `5000` | Maximum issue body length for express eligibility (0 = no limit) |
| `model` | string | `""` | LLM model override for the express-path agent step |
| `timeout_minutes` | integer | `15` | Max wall-clock time for the `create-implementation` step |
| `comment_on_classification` | boolean | `true` | Whether to post the classification rationale as an issue comment (FR-05) |

**Config consumption:** The `defaults.express.eligibility.*` keys are consumed by the triage flow's `on_outcome` handler in `flows.yml`, which reads the verdict and the config to decide whether to set `llmaw:express-eligible` or `llmaw:feature-request`. The `model` and `timeout_minutes` keys are read by the GitHub Actions workflow (`dispatch.yml`) which passes them as environment variables to the `create-implementation` agent step — the same mechanism used by the existing `defaults.model` and `defaults.timeout_minutes` patterns. The `comment_on_classification` key is consumed by the triage flow's `on_outcome` handler to decide whether to post the classification rationale.

All config keys are read by deterministic steps (shell or labels steps) in flows.yml, not by `engine.py`. This keeps the engine generic and unchanged.

**Forward compatibility:** Consumers MUST ignore unknown keys within `defaults.express`. New eligibility criteria fields may be added without breaking existing configs.

### triage-issue Skill — Extended Verdict Contract

The skill's output schema is extended additively. Existing consumers that only read `verdict` continue to work unchanged.

| Field | Type | Required | Description |
|---|---|---|---|
| `verdict` | string | Yes | `feature`, `bug`, `needs-info`, `other` |
| `complexity` | string | No | `low`, `medium`, `high`. Defaults to absent (not eligible for express path). |
| `reason` | string | No | Explanation of the classification |

**Forward compatibility:** The verdict YAML may contain additional top-level fields. Consumers MUST ignore fields they do not recognize.

**Classification logging (FR-05):** When `defaults.express.comment_on_classification` is `true` (the default), the triage-flow `on_outcome` posts an issue comment recording the classification decision and its rationale. The comment format:

> **Express Path Classification**
> - Verdict: feature
> - Complexity: low
> - Reason: Single-file change with clear scope; no cross-cutting concerns.
> - Route: Express path enabled.

When `complexity` is absent or the issue is ineligible, the comment instead states why the express path was not chosen. This satisfies FR-05's requirement to log the classification decision to the issue.

### Outcome Verdict Contract

The `create-implementation` skill must emit one of:

| Verdict | Meaning |
|---|---|
| `approved` | Implementation succeeded, PR created |
| `failed` | Implementation could not complete |

`on_outcome` in the express flow maps these to label transitions.

**Forward compatibility:** New verdict values may be added. The `on_outcome` default case (`_`) catches unhandled values and must not crash.

### create-implementation — Minimum Interface Contract

The express path depends on the `create-implementation` skill functioning without upstream planning artifacts. The contract it must satisfy:

**Inputs available:**

| Input | Source | Required | Description |
|---|---|---|---|
| Issue body | `ISSUE_BODY` env var | Yes | Full issue description text |
| Issue title | `ISSUE_TITLE` env var | Yes | Issue title |
| Issue labels | `ISSUE_LABELS` env var | Yes | Comma-separated current labels |
| PR branch | Standard workflow inputs | Yes | Branch created by `ensure-branch.sh` |
| `.sdlc/` context | Filesystem | No | May be absent; skill must tolerate missing `.sdlc/` directories gracefully |
| Requirements/specs | Filesystem | No | Must NOT be required; skill must work from issue body alone |

**Behavioral contract:**

1. The skill MUST produce working code changes (implementation + tests) when the scope is "simple" (single-file or few-file change with clear requirements in the issue).
2. The skill MUST write its outcome to `$OUTCOME_YAML` (verdict: `approved` | `failed`).
3. The skill MUST create a PR on success (by invoking `create-pr` or `gh` internally). The PR title defaults to the issue title; the PR body links to the issue.
4. The skill MUST NOT require any `.sdlc/` artifact beyond what the express path produces (`express-decision.md`).
5. If the skill cannot produce an implementation (ambiguous requirements, missing context), it MUST emit `verdict: failed` with a descriptive `reason` rather than crashing or producing a partial PR.

**GitHub token scope requirement:** The GITHUB_TOKEN used in the Actions workflow must have `contents: write` (to push the implementation branch) and `pull-requests: write` (to create the PR). These are the default scopes for `GITHUB_TOKEN` in public repositories. For private repositories, the workflow must explicitly grant these scopes.

**Verification:** Before enabling the express path on real issues, run the `create-implementation` skill against 3-5 historical issues whose PRs were implemented via the full pipeline. Compare the express-path output with the actual implementation. If the skill fails on any of these test cases, either modify the skill to tolerate missing artifacts or add a pre-step that synthesizes minimal context from the issue body.

## Sequences

### Happy Path: Auto-Classified Express Feature

```
Issue Opened
  |
  |--- dispatch.yml triggers triage flow
  |
  |--- triage-issue skill runs
  |     verdict: feature
  |     complexity: low
  |
  |--- on_outcome matches new case:
  |     sets llmaw:express-eligible
  |     removes llmaw:feature-request
  |
  |--- issue labeled event fires
  |
   |--- dispatch.yml matches express flow
   |     rule: express-implement-from-eligible
   |
   |--- create-implementation skill runs
   |     input: issue body + labels only
   |     produces: implementation + tests
   |     creates PR via create-pr skill (inside agent step)
   |
   |--- on_outcome: approved
   |     sets llmaw:express-done
   |     posts comment: "Implementation ready at PR #<N>"
   |
   |--- PR review follows existing review flow
```

### Manual Override: Human Labels Issue

```
Human adds llmaw:quick-implement label to an issue
  |
  |--- issue labeled event fires
  |
   |--- dispatch.yml matches express flow
   |     rule: express-quick-implement
   |     (matches on llmaw:quick-implement, no triage needed)
  |
  |--- create-implementation skill runs
  |
  |--- same outcome path as happy path
```

### Failure: Express Implementation Fails

```
...express flow matched, create-implementation runs...
  |
  |--- create-implementation encounters error
  |     (ambiguous requirements, dependency issues, etc.)
  |
  |--- on_outcome: failed
  |     sets llmaw:express-failed
  |     posts comment: "Express path could not implement.
  |                     Reason: <details>."
  |     does NOT fall back to full pipeline
  |     (per FR-02 execution failure AC)
```

### Express Label Removed: Fallback to Full Pipeline (FR-06 Inverse)

```
Issue has llmaw:express-eligible label
  |
  |--- Human removes llmaw:express-eligible label
  |     (or llmaw:quick-implement was removed)
  |
  |--- issue labeled event fires (labeled: removed)
  |
   |--- dispatch.yml runs route.py
   |     express-implement-from-eligible rule does NOT match
   |     (requires llmaw:express-eligible to be present)
  |
  |--- If issue has llmaw:feature-request or no express label:
  |     falls through to default routing
  |
  |--- Next pipeline cycle triggers full triage -> feature flow
  |     (assuming re-classification yields "feature" verdict)
  |
  |--- Full SDLC pipeline runs as normal
```

Note: removing `llmaw:express-eligible` or `llmaw:quick-implement` does NOT automatically trigger the full pipeline. The issue must go through the normal triage flow on the next event cycle. If the issue already has `llmaw:feature-request` (from an earlier triage pass), it is picked up by the feature flow on the next matching event.

### Ineligible Issue: Full Pipeline

```
Issue Opened
  |
  |--- dispatch.yml triggers triage flow
  |
  |--- triage-issue skill runs
  |     verdict: feature
  |     [complexity absent or complexity: high]
  |
  |--- on_outcome matches existing feature case
  |     sets llmaw:feature-request
  |     (no change from current behavior)
  |
  |--- full SDLC pipeline runs as before
```

## Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Flow model | New `express` flow in `flows.yml` | Mirrors the existing bugfix pattern; requires zero engine changes; orthogonal to existing flows |
| Classification timing | At triage time, inside `triage-issue` skill | Single pass is more efficient than a separate classification step; the triage agent already reads the issue for classification |
| Complexity verdict | Optional `complexity` field in existing YAML | Backward compatible; old consumers ignore it; absent value means "not express-eligible" |
| Human override | `llmaw:quick-implement` label | Matches the `gate:auto` pattern from existing solutions; integrated via `when.label` in a dedicated rule; zero code changes to add |
| Metrics | Label-based query via `gh issue list --label llmaw:express-done` | Zero infrastructure; leverages existing GitHub query capabilities; defer dashboard until usage warrants |
| Artifact trail | Minimal `express-decision.md` + terminal label | Satisfies traceability requirement (FR-03) without enforcing a full `.sdlc/` branch cycle |
| Failure handling | Terminal label + comment; NO fallback to full pipeline | Prevents infinite loops; failure is surfaced to humans for manual intervention per requirements |
| Configurable criteria | `defaults.express` block in `flows.yml` | Follows existing pattern for engine config (models, timeouts); criteria can be tuned without code changes |
| Cross-repo deployment | Update `triage-issue` skill first, then add express flow | The express flow treats absent `complexity` as "not eligible." If the flow ships before the skill, issues simply never match the express rule — safe degradation. If the skill ships first, the `complexity` field is emitted but no flow consumes it yet — also safe. Either order is safe because the contract is backward compatible. |
| PR ownership | `create-implementation` agent step invokes `create-pr` or `gh` internally | The agent step has access to the implementation branch and commit SHA after producing code changes. Delegating PR creation to `on_outcome` would require the agent to write state for the engine to read, adding complexity. |
| Anti-spoofing | Label compartmentalization (two distinct labels for auto vs. manual); no origin verification in engine | The engine's `matches()` cannot verify label origin. Using two different labels (`llmaw:express-eligible` auto-only, `llmaw:quick-implement` human-only) separates the paths by name, requiring zero engine changes. Audit trail via issue timeline provides post-hoc verification. |
| Express flow rules | Two separate rules (`express-implement-from-eligible`, `express-quick-implement`) | The engine's `When` dataclass uses `label: str | None` (singular). A single rule cannot match two different labels. Two rules mirror the existing pattern and require no engine changes. |
| Config consumption | Deterministic steps in flows.yml; not engine.py | The engine is generic and reads only `model` and `timeout_minutes` from `defaults`. Express-specific eligibility config is consumed by the triage `on_outcome` handler (shell/labels steps) and `dispatch.yml` (env vars). This keeps the engine unchanged. |
| `issues:opened` trigger | Not used; `issues:labeled` is the sole trigger | On `issues:opened`, the label is absent (triage runs first and sets it). The `issues:labeled` event fires after triage sets the label, providing a clean match. The `issues:opened` event that carries a pre-applied `llmaw:quick-implement` label is theoretically possible but not the design target. |

## Risks and Unknowns

1. **`create-implementation` skill depends on upstream artifacts.** The core risk (also identified in codebase analysis): `create-implementation` may fail or produce low-quality output when no requirements, specifications, or codebase-analysis artifacts exist. Mitigation: verify this through testing before enabling the express path on real issues; the failure outcome (`llmaw:express-failed`) provides a safe abort path. If the dependency is hard (skill crashes without the artifacts), the express path cannot ship without modifying `create-implementation` to tolerate their absence.

2. **Coordination between two repositories.** The `triage-issue` skill lives in `tomzx/agents` while the express flow lives in this repository. Adding `complexity` to the triage verdict requires coordinated deployment: the skill must be updated first (or the express flow must handle the field's absence gracefully, which it does via the "absent means not eligible" default). Either order is safe: if the flow ships first, issues simply never match the express rule; if the skill ships first, the field is emitted but unused. The deployment ordering risk is low.

3. **Classification accuracy at triage time.** The triage agent's ability to assess complexity from the issue body alone may be limited (80%+ F1 per academic benchmarks). False positives (a complex feature labeled as low complexity) would produce a failed implementation attempt. The failure path handles this gracefully, but repeated failures may erode trust in the express path.

4. **Token cost of the minimal artifact.** Writing `express-decision.md` costs tokens on every express-path feature. For high-volume usage this could negate some of the token savings from skipping planning phases. Mitigation: if usage is high, the artifact can be deferred to a post-hoc aggregation step.

5. **Label namespace collisions.** The new labels must not overlap with existing `llmaw:*` labels. The existing-solutions survey and codebase analysis confirm no collisions with current label definitions, but future label additions must respect the namespace.

6. **Terminal labels are one-way doors.** Once `llmaw:express-done` or `llmaw:express-failed` is set, the flow engine will not re-process the issue through any path (express or full) without human removal of the terminal label. This is by design — it prevents infinite loops — but means a human must intervene to retry a failed express-path issue. This is a design commitment, not a bug.

7. **`express-decision.md` persists if issue is later re-processed.** If an issue gets `llmaw:express-failed` and a human removes the label and triggers the full pipeline, the old `express-decision.md` artifact remains with a `failed` outcome. This is acceptable for traceability (readers see the failed attempt) but must be documented to avoid confusion.

8. **NFR-01 token savings target.** The express path must consume at most 60% of the full pipeline's token count for comparable features. Measurement: capture total token usage from the agent step's LLM API call metadata (input + output tokens) for both the express path and a comparable full-pipeline feature. Compare after each run. If the target is not met after 5 runs, re-evaluate the scope of what is classified as "low complexity." The first 5 express-path runs against historical issues establish the initial baseline; the target is confirmed when a two-tailed t-test (p < 0.05) shows the express path uses significantly fewer tokens than full-pipeline runs for similar issues.

9. **NFR-02 code quality verification.** The express path's output must pass the same CI checks as full-pipeline output (lint, typecheck, tests). The PR created by the express path triggers the normal CI workflow. Additionally, before the express path ships to production, run a manual quality comparison: take 3 express-path PRs for historical features and have a human reviewer assess whether the code quality is equivalent to what the full pipeline would produce. If any of the 3 PRs is rejected for quality reasons, defer the express path until the quality gap is closed (e.g., by tuning the LLM prompt or tightening the classification criteria).

## Out of Scope

- Metrics dashboard or automated reporting (FR-07 deferred to label-query approach)
- Changes to the `create-implementation` skill (tested as-is, modified separately if needed)
- Changes to the existing `feature` or `bugfix` flows
- Non-GitHub triggers or external service integration
- Automatic retry of failed express-path implementations
- Quality comparison or A/B testing between express path and full pipeline
