---
issue: "#17"
title: "Implement directly from issue"
status: draft
---

# Specification: Implement directly from issue

## Overview

The express path adds a lightweight third flow to the existing label-driven state machine (`flows.yml`) that routes eligible issues directly from triage to implementation, skipping all intermediate planning phases. The triage-issue skill is extended to emit a `complexity` verdict field; issues classified as `feature` + `complexity: low` are labeled `llmaw:express-eligible` and matched by a new `express` flow rule that runs only `create-implementation`. A human-applied `llmaw:quick-implement` label bypasses automatic classification. The existing `feature` and `bugfix` flows are unchanged, and all engine internals (`engine.py`, `route.py`, `run_rule.py`, `run_steps.py`, `apply_outcome.py`) are reused as-is.

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

| Label | Type | Description |
|---|---|---|
| `llmaw:express-eligible` | Milestone (transient) | Set automatically when triage classifies issue as feature + low complexity |
| `llmaw:quick-implement` | Human-applied | Manual override: routes any issue through the express path regardless of triage verdict |
| `llmaw:express-done` | Terminal | Set when express-path implementation succeeds and a PR is created |
| `llmaw:express-failed` | Terminal | Set when express-path implementation fails |

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
path: express
implemented_from: issue #<N>
trigger: classification | manual
complexity: low | medium | high
implemented_at: <ISO datetime>
outcome: success | failed
pr_url: <url>  # present on success
---
```

## API Contracts

This feature does not introduce new HTTP APIs. The contract surface is:

### flows.yml — New Express Flow

A new `express` top-level key in `flows.yml` with rules that match on `llmaw:express-eligible` or `llmaw:quick-implement` labels. The flow follows the same rule schema as the existing `feature` and `bugfix` flows.

**Rule: `express-implement-from-issue`**

| Field | Value |
|---|---|
| `when.event` | `issues:labeled`, `issues:opened` |
| `when.labels` | `llmaw:express-eligible`, `llmaw:quick-implement` |
| `steps.agent` | `create-implementation` |
| `on_outcome.approved` | Set `llmaw:express-done`, create PR |
| `on_outcome.failed` | Set `llmaw:express-failed`, comment error |

**Forward compatibility:** Consumers must ignore unknown fields in any rule schema. New label values may be added to the `when.labels` list without breaking existing rules.

### triage-issue Skill — Extended Verdict Contract

The skill's output schema is extended additively. Existing consumers that only read `verdict` continue to work unchanged.

| Field | Type | Required | Description |
|---|---|---|---|
| `verdict` | string | Yes | `feature`, `bug`, `needs-info`, `other` |
| `complexity` | string | No | `low`, `medium`, `high`. Defaults to absent (not eligible for express path). |
| `reason` | string | No | Explanation of the classification |

**Forward compatibility:** The verdict YAML may contain additional top-level fields. Consumers MUST ignore fields they do not recognize.

### Outcome Verdict Contract

The `create-implementation` skill must emit one of:

| Verdict | Meaning |
|---|---|
| `approved` | Implementation succeeded, PR created |
| `failed` | Implementation could not complete |

`on_outcome` in the express flow maps these to label transitions.

**Forward compatibility:** New verdict values may be added. The `on_outcome` default case (`_`) catches unhandled values and must not crash.

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
  |     rule: express-implement-from-issue
  |
  |--- create-implementation skill runs
  |     input: issue body + labels only
  |     produces: implementation + tests
  |
  |--- on_outcome: approved
  |     sets llmaw:express-done
  |     creates PR via create-pr skill
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
  |     rule: express-implement-from-issue
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
| Human override | `llmaw:quick-implement` label | Matches the `gate:auto` pattern from existing solutions; integrates with `when.labels` matching; zero code changes to add |
| Metrics | Label-based query via `gh issue list --label llmaw:express-done` | Zero infrastructure; leverages existing GitHub query capabilities; defer dashboard until usage warrants |
| Artifact trail | Minimal `express-decision.md` + terminal label | Satisfies traceability requirement (FR-03) without enforcing a full `.sdlc/` branch cycle |
| Failure handling | Terminal label + comment; NO fallback to full pipeline | Prevents infinite loops; failure is surfaced to humans for manual intervention per requirements |
| Configurable criteria | `defaults.express` block in `flows.yml` | Follows existing pattern for engine config (models, timeouts); criteria can be tuned without code changes |

## Risks and Unknowns

1. **`create-implementation` skill depends on upstream artifacts.** The core risk (also identified in codebase analysis): `create-implementation` may fail or produce low-quality output when no requirements, specifications, or codebase-analysis artifacts exist. Mitigation: verify this through testing before enabling the express path on real issues; the failure outcome (`llmaw:express-failed`) provides a safe abort path.

2. **Coordination between two repositories.** The `triage-issue` skill lives in `tomzx/agents` while the express flow lives in this repository. Adding `complexity` to the triage verdict requires coordinated deployment: the skill must be updated first (or the express flow must handle the field's absence gracefully, which it does via the "absent means not eligible" default).

3. **Classification accuracy at triage time.** The triage agent's ability to assess complexity from the issue body alone may be limited (80%+ F1 per academic benchmarks). False positives (a complex feature labeled as low complexity) would produce a failed implementation attempt. The failure path handles this gracefully, but repeated failures may erode trust in the express path.

4. **Token cost of the minimal artifact.** Writing `express-decision.md` costs tokens on every express-path feature. For high-volume usage this could negate some of the token savings from skipping planning phases. Mitigation: if usage is high, the artifact can be deferred to a post-hoc aggregation step.

5. **Label namespace collisions.** The new labels must not overlap with existing `llmaw:*` labels. The existing-solutions survey and codebase analysis confirm no collisions with current label definitions, but future label additions must respect the namespace.

## Out of Scope

- Metrics dashboard or automated reporting (FR-07 deferred to label-query approach)
- Changes to the `create-implementation` skill (tested as-is, modified separately if needed)
- Changes to the existing `feature` or `bugfix` flows
- Non-GitHub triggers or external service integration
- Automatic retry of failed express-path implementations
- Quality comparison or A/B testing between express path and full pipeline
