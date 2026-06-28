---
title: "Flow Configuration and Routing"
status: approved
---

# Specification: Flow Configuration and Routing

## Overview

The routing core is a pure Python module (`engine.py`) plus a thin CLI (`route.py`) that reads the GitHub event from the Actions runtime environment, runs the matcher, and writes the matrix to `$GITHUB_OUTPUT`.
It owns the `flows.yml` schema, the `When`/`Rule`/`AgentStep` value types, step normalization, `on_outcome` validation, the label-diff helper, and execution-mode resolution.

## Architecture

```
flows.yml
   |
   v
engine.load_flows  ->  engine.flatten_rules(defaults, base_model, base_agents_repo)
                          |-- parse_when per rule
                          |-- normalize_run + split_steps (pre / agent / post / on_outcome)
                          |-- build_agent (override > defaults > base)
                          v
                       list[Rule]
   |
   v  (route.main)
engine.matches(when, GITHUB_EVENT_NAME, payload)  for each rule
   |
   v
[rule_to_matrix(r) for r in matched]
   |
   v
GITHUB_OUTPUT: matched (JSON), count, has_agent, execution   (+ $MATCHED_FILE)
```

## Data Models

### `When`

| Field | Type | Constraints | Description |
|---|---|---|---|
| event | str \| None | one of the GitHub event names | Matched against `GITHUB_EVENT_NAME` |
| action | str \| None | - | Matched against `payload.action` |
| label | str \| None | - | Matched against `payload.label.name` |
| merged | bool \| None | - | Matched against `payload.pull_request.merged` |
| branch_prefix | str \| None | - | PR head `ref` must start with this prefix |
| body_contains | str \| None | - | Substring that must appear in issue/PR body |

### `AgentStep`

| Field | Type | Constraints | Description |
|---|---|---|---|
| kind | str | `skill` \| `prompt` | Discriminates the agent step |
| ref | str | non-empty | Skill command name or prompt file path |
| model | str | non-empty | opencode model id (provider/model) |
| agents_repository | str | non-empty | `owner/repo` providing skills |
| timeout_minutes | int \| None | - | Per-step timeout override |

### `Rule`

| Field | Type | Constraints | Description |
|---|---|---|---|
| id | str | unique | Rule identifier used in logs and the matrix |
| flow | str | - | Owning flow name (organizational) |
| when | When | - | Event matcher |
| deterministic | list[dict] | - | Pre-agent `labels`/`shell` steps |
| agent | AgentStep \| None | at most one | The agent step, if any |
| post_deterministic | list[dict] | - | Post-agent `labels`/`shell` steps |
| on_outcome | dict \| None | `{cases, default}` | Verdict-to-action switch |

## API Contracts

This feature has no HTTP API. Its contract is the CLI exit code and the GitHub Actions outputs it writes.

### `llmaw route` (env-driven)

**Inputs (environment)**

| Field | Type | Required | Description |
|---|---|---|---|
| GITHUB_EVENT_NAME | str | yes | GitHub event name (or `workflow_dispatch` for dry-run) |
| GITHUB_EVENT_PATH | path | no | Path to the event payload JSON |
| FLOWS_FILE | path | no (default `.github/llmaw/flows.yml`) | Config file to load |
| MODEL | str | no | Hardcoded base model fallback |
| AGENTS_REPOSITORY | str | no | Hardcoded base agents repo fallback |
| FORCE_RULE_ID | str | no | Dry-run: force-run a single rule by id |
| EXECUTION | str | no | Forced execution mode override |
| MATCHED_FILE | path | no | Where to mirror the `matched` JSON |

**Outputs (`$GITHUB_OUTPUT`) and stdout**

| Field | Type | Description |
|---|---|---|
| matched | JSON array | The matched rules as matrix entries |
| count | int | Number of matched rules |
| has_agent | bool | True if any matched rule has an agent step |
| execution | str | Resolved dispatch execution mode |

**Error Responses**

| Status | Code | Description |
|---|---|---|
| exit 1 | ConfigError | Invalid `flows.yml` (logged, no matrix emitted) |

## Sequences

### Match and dispatch

```
GitHub event -> dispatch.yml sets GITHUB_EVENT_NAME/GITHUB_EVENT_PATH
            -> llmaw route
            -> load_flows -> flatten_rules
            -> matches(when, event, payload) for each rule
            -> rule_to_matrix -> write matched/count/has_agent/execution
            -> Run matched rules step (skipped when count == 0)
```

### Dry-run

```
workflow_dispatch with rule-id input
            -> FORCE_RULE_ID set, GITHUB_EVENT_NAME == workflow_dispatch
            -> rules filtered by id (no event matching)
            -> single-rule matrix emitted
```

## Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Pure core | `engine.py` has no side effects | Enables direct unit testing of matchers and normalization |
| Routing is flat | Rules across all flows are flattened | Flow grouping stays organizational; routing is one deterministic pass |
| AND-only matchers | All `when` fields ANDed, unspecified are wildcards | Predictable, easy to reason about, covers observed needs |
| Matrix output | JSON array via `$GITHUB_OUTPUT` | Standard Actions pattern for a matrix over matched rules |

## Risks and Unknowns

1. OR-style matching is not supported; flows that need "match label A or B" must use separate rules.
2. `body_contains` performs a naive substring match on the issue/PR body, which can be expensive on very large bodies.

## Out of Scope

- Executing steps (handled by FEAT-0002).
- Continuous chaining logic (handled by FEAT-0003).
- Label creation/migration (handled by FEAT-0004).
- The dispatcher workflow itself (handled by FEAT-0005).
