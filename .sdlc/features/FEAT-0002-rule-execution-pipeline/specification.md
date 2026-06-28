---
title: "Rule Execution Pipeline"
status: approved
---

# Specification: Rule Execution Pipeline

## Overview

The pipeline driver is `run_rule.py` (`llmaw run-rule`). It reads matched rules from `$MATCHED_FILE` or `$MATCHED_RULE`, resolves the execution mode, and runs each rule's whole `run` through shared helpers: `run_steps.py` for deterministic `labels`/`shell` steps, an inline `opencode run` invocation for the agent step, and `apply_outcome.py` for the `on_outcome` switch.
GitHub mutations use the `gh` CLI with `GH_TOKEN`; the agent uses `opencode` with the configured model.

## Architecture

```
run_rule.main
  |-- _read_rules (MATCHED_FILE | MATCHED_RULE)
  |-- _resolve_execution -> event-driven | continuous (FEAT-0003)
  +-- per rule: _execute_rule
        ::group:: "Rule <id> (<flow>)"
        pre deterministic   -> run_steps.apply_labels / run_steps.run_shell
        reset $OUTCOME_YAML
        agent               -> subprocess: opencode run --model ... --command <skill>
        post deterministic  -> run_steps.apply_labels / run_steps.run_shell
        on_outcome          -> if outcome incomplete: _continue_for_outcome (opencode run --continue)
                            -> apply_outcome.apply(on_outcome, rid)
        ::endgroup::
```

## Data Models

### Matched rule matrix entry (consumed by `run-rule`)

| Field | Type | Constraints | Description |
|---|---|---|---|
| id | str | - | Rule id |
| flow | str | - | Owning flow |
| has_deterministic | bool | - | Whether pre deterministic steps exist |
| has_agent | bool | - | Whether an agent step exists |
| has_post_deterministic | bool | - | Whether post deterministic steps exist |
| has_on_outcome | bool | - | Whether an `on_outcome` step exists |
| deterministic | list[dict] | normalized | Pre-agent `labels`/`shell` steps |
| post_deterministic | list[dict] | normalized | Post-agent `labels`/`shell` steps |
| agent | dict \| null | `{kind, ref, model, agents_repository, timeout_minutes}` | The agent step |
| on_outcome | dict \| null | `{cases, default}` | Verdict-to-action switch |

### `$OUTCOME_YAML` (written by the skill, read by `on_outcome`)

| Field | Type | Constraints | Description |
|---|---|---|---|
| verdict | str | required | The domain decision the cases switch on |
| reason | str | required | Context-specific feedback; overrides the action's `comment` when `post_reason` is set |

### `on_outcome` action (per verdict case)

| Field | Type | Description |
|---|---|---|
| labels | `{add, remove, target}` | Label operation, same shape as a `labels` step |
| close | bool | Close the subject |
| comment | str \| None | Hardcoded comment body (fallback when `post_reason` and no reason) |
| post_reason | bool | Post the outcome `reason` instead of the hardcoded `comment` |

## API Contracts

No HTTP API. The contract is the CLI commands and their environment.

### `llmaw run-rule`

**Inputs (environment)**

| Field | Type | Required | Description |
|---|---|---|---|
| MATCHED_FILE | path | one of | File holding the matched-rule JSON array |
| MATCHED_RULE | json | one of | A single matched-rule JSON object |
| EXECUTION | str | no | Forced execution mode |
| OUTCOME_YAML | path | no | Where the agent writes its verdict |
| GH_TOKEN | str | yes | Token for `gh` mutations |
| ISSUE_NUMBER / PR_NUMBER | int | one of | The subject |
| plus all context vars | various | - | ISSUE_TITLE, PR_TITLE, COMMENT_BODY, ... |

### `llmaw run-steps [pre|post]`

**Inputs (environment)**

| Field | Type | Required | Description |
|---|---|---|---|
| MATCHED_RULE | json | yes | The matched-rule matrix entry |
| GH_TOKEN | str | yes | Token for `gh` |
| ISSUE_NUMBER / PR_NUMBER | int | yes | The subject |
| LLMAW_TOOLING_ROOT | path | no | Snapshot root for resolving `shell` scripts |

**Behavior**: applies the `deterministic` (pre) or `post_deterministic` (post) steps in order.

### `llmaw apply-outcome`

Reads `MATCHED_RULE` + `$OUTCOME_YAML` and applies the `on_outcome` action for the emitted verdict.

## Sequences

### Outcome continuation (incomplete outcome)

```
agent runs -> $OUTCOME_YAML missing or lacks verdict/reason
            -> _continue_for_outcome: opencode run --continue --model ... <prompt>
               (asks the model to write {verdict, reason} in the exact format)
            -> apply_outcome.apply(on_outcome) reads outcome -> selects action -> applies
```

### Linked-issue label step

```
labels step target=linked-issue
  -> _find_linked_issue: regex PR_TITLE/PR_BODY for closes|fixes|resolves|plan for issue #N (else first #N)
  -> compute_label_diff(current, add, remove)
  -> gh issue edit <N> --add-label / --remove-label
```

## Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| One driver command | `llmaw run-rule` replaced the former per-step Actions steps | One process runs the whole pipeline; fewer checkout/setup rounds |
| `gh` for mutations | Shell out to `gh` with `GH_TOKEN` | Reuses GitHub's auth, idempotent label edit semantics |
| Outcome continuation | Resume the opencode session once | Gives the model a chance to fix a missing/incomplete outcome before fallback |
| `post_reason` | Opt-in per action | Skill feedback surfaces when wanted; actions can stay silent or use hardcoded text |
| Run-link footer | Appended to every comment in Actions | Traceability from a posted comment back to the workflow run |

## Risks and Unknowns

1. The outcome continuation spends an extra agent invocation when the skill forgets the outcome; a persistently non-compliant skill will still hit the fallback.
2. `_find_linked_issue` falls back to the first `#N` in the PR text, which could misidentify the linked issue on ambiguous PR bodies.
3. The `shell` step runs scripts with `bash` and inherits the full environment; a misconfigured script can mutate state outside the engine's control.

## Out of Scope

- Continuous-mode chaining loop (handled by FEAT-0003).
- The routing that produces the matched rules (handled by FEAT-0001).
- The dispatcher workflow that installs opencode and skills (handled by FEAT-0005).
