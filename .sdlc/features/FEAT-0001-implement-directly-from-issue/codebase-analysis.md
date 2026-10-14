---
issue: "#17"
title: "Implement directly from issue"
status: approved
---

# Codebase Analysis: Implement directly from issue

## Overview

The feature adds an express pipeline path that routes eligible issues directly from triage to implementation, skipping the 14+ planning phases. The codebase is a config-driven label-state-machine engine (`flows.yml` + `engine.py`) that already implements a full feature pipeline and a bug-fix fast path. The express path is a third parallel flow that reuses the existing routing, matching, and execution machinery without any engine-level changes. The primary components to touch are `flows.yml` (add new labels and a new `express` flow), and the external `triage-issue` skill (extend its classification verdict to include complexity). All engine internals — `engine.py`, `route.py`, `run_rule.py`, `run_steps.py`, `apply_outcome.py` — are **reuse as-is**. The blast radius is narrow because the new flow adds rules that fire on new labels, and existing feature/bugfix rules are unchanged.

## Scope of Analysis

**Entry points and searches:**
- `grep .github/llmaw/flows.yml` — full flow configuration (triage, feature, bugfix, review)
- `read src/llm_augmented_workflows/*.py` — engine internals (route, run_rule, run_steps, apply_outcome, sync_labels, cli)
- `read .github/workflows/dispatch.yml` — GitHub Actions orchestrator
- `read .github/llmaw/scripts/*.sh` — working-branch scripts
- `read tests/test_engine.py tests/test_run_rule.py` — existing test coverage
- `read .sdlc/features/FEAT-0001/requirements.md` — requirements
- `read .sdlc/features/FEAT-0001/existing-solutions.md` — existing-solutions survey

**Areas examined:**
1. Flow configuration (`flows.yml`) — all 3 flows + triage + review
2. Engine core (`engine.py`) — loading, matching, step resolution
3. CLI routing (`route.py`) — event-to-rule matching
4. Rule execution (`run_rule.py`) — step ordering and dispatch
5. Deterministic steps (`run_steps.py`) — label/shell execution
6. Outcome handling (`apply_outcome.py`) — verdict-based routing
7. GitHub Actions dispatcher (`dispatch.yml`) — event-driven orchestration
8. Branch management scripts (`ensure-branch.sh`, `commit-sdlc.sh`)
9. Label syncing (`sync_labels.py`)

**Explicitly out of scope:**
- The `triage-issue`, `create-implementation`, and other skill implementations in the external agents repository (`tomzx/agents`). This analysis documents the integration points but does not analyze skill internals.
- Metrics reporting (FR-07): defined as "label query" in the existing-solutions survey; no codebase component exists yet.
- Non-GitHub triggers or external services.

## Relevant Existing Components

| Component | Path | Responsibility | Interaction |
|---|---|---|---|
| **Triage flow** | `.github/llmaw/flows.yml:183-196` | Classify new issues as feature/bug/needs-info/other | **Extend** — add complexity dimension to classification |
| **Feature flow** | `.github/llmaw/flows.yml:198-475` | Full 14+ phase SDLC pipeline for complex features | **Reuse as-is** — unchanged |
| **Bugfix flow** | `.github/llmaw/flows.yml:476-521` | Fast path for bugs: duplicate-check -> reproduce -> fix | **Reuse as-is** — orthogonal |
| **Review flow** | `.github/llmaw/flows.yml:523-536` | Automated PR review and comment handling | **Reuse as-is** — express impl PRs use same review path |
| **Label definitions** | `.github/llmaw/flows.yml:82-180` | Declares all `llmaw:*` labels for auto-sync | **Extend** — add express-path labels |
| **Engine core** | `src/llm_augmented_workflows/engine.py` | Load flows.yml, match events to rules, normalize steps | **Reuse as-is** — generic; new flows work without changes |
| **Route CLI** | `src/llm_augmented_workflows/route.py` | Read GITHUB_EVENT_NAME, match rules, emit matrix | **Reuse as-is** — reads flows.yaml generically |
| **Rule runner** | `src/llm_augmented_workflows/run_rule.py` | Execute pre -> agent -> post -> on_outcome pipeline | **Reuse as-is** — ordering unchanged |
| **Deterministic steps** | `src/llm_augmented_workflows/run_steps.py` | Apply labels/shell steps via gh CLI | **Reuse as-is** — labels/shell still work identically |
| **Outcome applier** | `src/llm_augmented_workflows/apply_outcome.py` | Read $OUTCOME_YAML verdict, apply labels/close/comment | **Reuse as-is** — same verdict pattern |
| **CLI dispatcher** | `src/llm_augmented_workflows/cli.py` | Subcommand routing for llmaw CLI | **Reuse as-is** — no new subcommands needed |
| **Label syncer** | `src/llm_augmented_workflows/sync_labels.py` | Create/update labels from flows.yml labels block | **Reuse as-is** — already generic |
| **GA dispatch workflow** | `.github/workflows/dispatch.yml` | Event-driven orchestrator: route, install tools, run rules | **Reuse as-is** — generic; new flows in flows.yml need no workflow changes |
| **Branch scripts** | `.github/llmaw/scripts/ensure-branch.sh`, `commit-sdlc.sh` | Manage per-issue sdlc/ working branch | **Reuse as-is** — express path still needs branch for artifact |
| **triage-issue skill** | external (`tomzx/agents`, skills/) | Classifies issue type and priority | **Extend** — add `complexity` field to verdict |

## Dependency and Coupling Map

```
GitHub event (issues: opened, labeled, ...)
  |
  v
  dispatch.yml  [REUSE]  -- generic orchestrator
  |
  v
  route.py -> engine.py  [REUSE]
    matches rules from flows.yml against event
  |
  v
  run_rule.py -> run_steps.py + apply_outcome.py  [REUSE]
    executes pre-labels/shell -> agent -> post-labels/shell -> on_outcome
  |
  +-- [if feature flow match]  -> 14+ create-* + review-* skills (external)
  +-- [if bugfix flow match]   -> 3 skills (check-duplicates, reproduce-issue, fix-issue)
  +-- [if express flow match]  -> 1 skill (create-implementation), NO intermediate phases
  +-- [if triage flow match]   -> triage-issue skill [EXTEND]
```

**Tight coupling:**
- The engine is tightly bound to the `flows.yml` schema (event matchers, step kinds, on_outcome verdicts). This is intentional and by design — `engine.py` is the single validator of that schema.
- `run_rule.py` is coupled to the matrix entry schema produced by `engine.rule_to_matrix()`. This is a stable internal contract.

**Shared state:**
- A label state machine on each issue. There is no database; GitHub labels and issue state are the sole persistence. The express path introduces new labels that are orthogonal to existing ones.
- The per-issue working branch (`sdlc/issue-N`) carries `.sdlc/` artifacts between rule runs. The express path may need a lightweight version of this (or skip the branch for zero-planning features).

**Synchronous vs. asynchronous boundaries:**
- All execution is synchronous within a single GitHub Actions job (max 60 min timeout). The express path is faster by design (fewer agent steps, same sync model).
- State transitions are asynchronous (one rule run emits a label, triggering the next rule on the next event). The express path collapses multiple label transitions into fewer steps, but the model is the same.

**Blast radius of changes:**
- Adding new labels: **none** — labels are independent, set via `labels:` block in flows.yml and synced by `sync_labels.py`.
- Adding new rules in an `express` flow: **none** — they only match their own labels; existing rules that match `llmaw:feature-request` or `llmaw:bug` are unaffected.
- Extending the triage verdict: **low** — existing feature flow rules react to the `feature` verdict, which is unchanged. Adding a `complexity` field alongside is a compatible extension.
- Changing the triage-issue skill: **low** — the skill output is structured YAML; extending its verdict vocabulary is backward-compatible. The `on_outcome` mapping would need new cases, but old cases still work.

## Changeability Assessment

### Flow configuration (flows.yml) — triage flow

- **Current state:** A single rule `triage-new-issue` that runs `triage-issue` skill and maps the verdict to `llmaw:feature-request`, `llmaw:bug`, `needs-info`, or `other`.
- **Change disposition:** Extend
- **Rationale:** The express path needs a complexity assessment at triage time. Per the existing-solutions survey recommendation, this can be achieved by extending the `triage-issue` skill's verdict to include a `complexity` field (low/medium/high) and adding a new rule (or extending the existing `on_outcome` mapping) that routes low-complexity feature issues to `llmaw:express-eligible` instead of `llmaw:feature-request`. Alternatively, a new rule `classify-express` could fire on `llmaw:feature-request` and decide express eligibility based on configurable criteria (labels, issue body length). Both approaches work within the existing `on_outcome` pattern.
- **Risk:** Low — the triage flow already classifies issues; adding a dimension is along an existing seam. The verdict schema is YAML and extends naturally.
- **Constraints:** The existing `on_outcome` must not break: the `feature` case must still work for complex features. The complexity verdict must be optional (MUST default to "not express-eligible" if absent) to maintain backward compatibility with the triage skill before it is updated.

### Flow configuration (flows.yml) — feature flow

- **Current state:** 14 create/review phase pairs chained via label milestones (`llmaw:needs-approved` -> `llmaw:requirements-approved` -> ... -> `llmaw:tests-approved` -> `feat-implementation`).
- **Change disposition:** Reuse as-is
- **Rationale:** The feature flow is unchanged. Complex features that are not express-eligible still traverse the full pipeline. The express path is an entirely new flow, not a modification of the existing one.
- **Risk:** None — no changes.
- **Constraints:** The express path must not emit labels that the feature flow accidentally matches (e.g., must not set `llmaw:feature-request` on issues that go through the express path).

### Flow configuration (flows.yml) — bugfix flow

- **Current state:** Bug fix fast path (duplicates -> reproduce -> fix), orthogonal to feature flows.
- **Change disposition:** Reuse as-is
- **Rationale:** Bug fix and express feature paths are independent. Bugs still go through the bugfix flow regardless of complexity.
- **Risk:** None.
- **Constraints:** The express path labels must not overlap with bugfix labels (`llmaw:bug`, `llmaw:bug-*`).

### Label definitions (flows.yml labels block)

- **Current state:** ~30 labels defined for triage, feature pipeline stages (transient + milestone), bugfix milestones, and human intervention.
- **Change disposition:** Extend
- **Rationale:** New labels are needed for the express path. Per FR-06, a human override label (e.g., `llmaw:quick-implement`) is also required. A "currently on express path" label may be used for traceability.
- **Risk:** Low — labels are additive, each with a unique name. `sync_labels.py` handles creation/update generically.
- **Constraints:** All labels must use the `llmaw:` prefix. No existing label names must be changed.

### Engine core (engine.py)

- **Current state:** Generic YAML loader, event matcher, step normalizer, and matrix builder. Handles any flow/rule structure defined in flows.yml.
- **Change disposition:** Reuse as-is
- **Rationale:** The engine is already fully generic. It does not know about specific flows or labels; it just matches `when` conditions against events and executes steps. New rules in a new `express` flow are loaded, matched, and serialized identically to existing rules.
- **Risk:** None.
- **Constraints:** None — the engine contract is stable.

### Route CLI (route.py)

- **Current state:** Reads GITHUB_EVENT_NAME and environment, calls `flatten_rules` and `matches`, writes matched rules to output.
- **Change disposition:** Reuse as-is
- **Rationale:** Same as engine.py — the router is generic. New rules match through the same code path.
- **Risk:** None.

### Rule runner (run_rule.py)

- **Current state:** Reads matched rules from `MATCHED_FILE`, loops through `_execute_rule` for each: pre deterministic steps -> agent -> post deterministic steps -> on_outcome.
- **Change disposition:** Reuse as-is
- **Rationale:** The execution pipeline (pre -> agent -> post -> outcome) is the same for every rule. The express path rules use the same pipeline.
- **Risk:** None.

### Deterministic steps (run_steps.py)

- **Current state:** Applies label diffs and runs shell scripts via `gh` CLI.
- **Change disposition:** Reuse as-is
- **Rationale:** Express path may use `labels` steps for label transitions and `shell` steps for branch management. The implementation is generic.
- **Risk:** None.

### Outcome applier (apply_outcome.py)

- **Current state:** Reads `$OUTCOME_YAML`, selects verdict action, applies labels/close/comment.
- **Change disposition:** Reuse as-is
- **Rationale:** The express path uses the same `on_outcome` mechanism for outcome-driven routing. The `on_outcome` schema is unchanged.
- **Risk:** None.

### GA dispatch workflow (dispatch.yml)

- **Current state:** Generic event-driven dispatcher: checkout -> route -> install opencode -> install skills -> run-rule matrix. Resolves `model` and `agents_repository` from inputs/vars/defaults, same as existing flows.
- **Change disposition:** Reuse as-is
- **Rationale:** The dispatcher's behavior is driven by the matched rules from `route.py`. New rules in the express flow are matched and executed by the same pipeline. No workflow-level changes are needed.
- **Risk:** None.

### Branch scripts (ensure-branch.sh, commit-sdlc.sh)

- **Current state:** `ensure-branch.sh` creates/checks out `sdlc/issue-N` branch; `commit-sdlc.sh` commits `.sdlc/` changes and pushes.
- **Change disposition:** Reuse as-is
- **Rationale:** The express path may still need a working branch if it produces the minimal artifact trail (FR-03). The scripts are generic and work with any branch named `sdlc/issue-N`.
- **Risk:** Low — if the express path produces zero `.sdlc/` artifacts, the branch scripts are no-ops (commit-sdlc exits early on empty diff). No harm in running them.

### Label syncer (sync_labels.py)

- **Current state:** Reads `labels:` block from flows.yml, creates/updates each label via `gh label`.
- **Change disposition:** Reuse as-is
- **Rationale:** Already generic; adding new labels in flows.yml is sufficient for auto-creation.
- **Risk:** None.

### triage-issue skill (external — agents repository)

- **Current state:** An opencode skill that reads an issue, produces a YAML verdict with `verdict: feature|bug|needs-info|other`.
- **Change disposition:** Extend
- **Rationale:** The skill needs to emit a `complexity: low|medium|high` field alongside its existing verdict. The express eligibility can be determined by the combination of `verdict: feature` + `complexity: low`. This is a backward-compatible extension: old consumers ignore the new field, and the express path checks it.
- **Risk:** Medium — the skill lives in a separate repository (`tomzx/agents`). Changes must be coordinated between this repo's express flow and the skill's verdict schema. A versioning or schema-detection mechanism may be needed to avoid race conditions during deployment.
- **Constraints:** The skill must continue to produce valid YAML with the existing `verdict` field. The `complexity` field must be optional (explicitly documented as MAY be present).

## Migration and Impact Considerations

### Express flow introduction

The new `express` flow does not replace or refactor any existing component. The only migrations are:

1. **triage-issue skill** — extend verdict schema to include `complexity`. This is a backward-compatible change: the `verdict: feature` output still works for the existing feature flow. The `complexity` field is additive. Rollout strategy: update the skill first, then add express flow rules. The express rules can check for `complexity: low`; if it is absent, the issue is not eligible and stays on the feature flow.

2. **flows.yml** — add new labels and the `express` flow. This is a purely additive config change. The new rules only fire on new labels; existing rules are untouched. Rollout: add to `flows.yml` in a single PR, then run `sync-labels` to create the new labels in the repository.

3. **De-risking:** Both changes are behind labels and never activate until an issue receives the express-path label (either automatically from triage or manually from a human via FR-06). The existing feature and bugfix flows continue working uninterrupted.

### Backward compatibility

- The existing feature flow is completely unchanged. Issues that reach `llmaw:feature-request` (the existing triage outcome for features) still traverse the full pipeline.
- The triage-issue skill's old verdict schema (without `complexity`) is still valid. The express flow rules simply do not match issues whose verdict lacks `complexity: low`.
- All existing labels, PR merge detectors, and terminal markers (`llmaw:shipped`, `llmaw:finished`, `llmaw:bug-fixed`) are unchanged.

## Assumptions About Existing Code

1. **The `triage-issue` skill can be extended to emit a `complexity` field.** The skill currently writes a YAML verdict to `$OUTCOME_YAML`. If the skill's implementation does not support structured output beyond a single `verdict` key, this assumption is wrong and the complexity classification would need a separate step. (Risk: medium — verified by reading the skill's contract: skills write arbitrary YAML to `$OUTCOME_YAML`.)

2. **The existing `on_outcome` mapping in the triage flow can be extended with additional verdict cases.** The triage flow currently maps `feature`, `bug`, `needs-info`, `other`, and `_`. Adding `feature-low-complexity` (or similar) as a new verdict case is within the existing schema. Verified by reading `engine.py`: `on_outcome` supports arbitrary verdict strings in its cases mapping.

3. **The express path's artifact trail can be written to `.sdlc/` with zero conflicts.** The working branch is `sdlc/issue-N`. The express path would write a lightweight record there. Since no other flow writes to the same issue's `.sdlc/` simultaneously (concurrency group per issue), conflicts are impossible.

4. **`create-implementation` skill works correctly without upstream planning artifacts.** The feature flow currently feeds artifacts (requirements, specifications, etc.) through the `.sdlc/` chain, building context for `create-implementation`. The express path skips those artifacts. The assumption is that `create-implementation` can produce a reasonable implementation from the issue alone when the scope is simple and well-defined. (Risk: high — this is the core risk of the express path. The skill must be verified to work in this context.)

## Open Questions

1. **How exactly does the triage-issue skill emit its verdict today, and what changes are needed to add `complexity`?** The exact YAML schema and whether the skill already has access to enough context for complexity classification (label presence, issue body, past patterns) determines whether extending the skill is trivial or requires a new classification step.

2. **Should express eligibility be decided inside the triage-issue skill (a single pass) or as a separate rule after triage (two passes)?** The existing-solutions survey identifies both options. A single pass is more efficient and simpler; a separate rule is more modular and allows re-running classification independently. This depends on how tightly coupled the complexity assessment is to the issue-type classification.

3. **What minimal artifact format does the express path produce?** FR-03 requires a minimal artifact record but does not specify its shape. Options: (a) a lightweight `.sdlc/features/FEAT-NNNN/express-decision.md` with classification rationale and timestamp, (b) an issue comment, or (c) a label. The choice affects whether the branch scripts (`ensure-branch.sh` / `commit-sdlc.sh`) are needed on the express path.

4. **Does `create-implementation` require artifacts (requirements, specifications, etc.) to function correctly?** The whole premise of the express path is that it does not for simple features. This must be verified by testing the skill against a feature issue with no upstream `.sdlc/` artifacts.

5. **What label slug should the manual override use?** The existing-solutions survey suggests `llmaw:quick-implement` (FR-06). This label must be defined in `flows.yml` labels block and added to the `when:` condition of the express path's implementation rule.
