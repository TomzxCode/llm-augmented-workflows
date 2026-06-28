---
title: "Continuous Execution Mode"
status: approved
---

# Specification: Continuous Execution Mode

## Overview

Continuous mode is implemented in `run_rule.py` (`_run_continuous`) plus the resolution helpers in `engine.py` (`parse_execution`, `resolve_execution_for_flow`, `resolve_dispatch_execution`, `find_next_rules`).
It wraps the rule pipeline (FEAT-0002) in a label-keyed loop that runs inside the same GitHub Actions job, re-reading the issue's labels after each iteration to pick the next rule.

## Architecture

```
run_rule.main
  |-- _resolve_execution (EXECUTION env or default)
  |-- if continuous: _run_continuous(seed_rules)
        subject = _current_subject()
        if not issue: run seed once, return              (FR-07)
        all_rules = _load_all_rules()                    (re-read flows.yml for chaining)
        seen = current issue labels
        batch = seed_rules
        loop (max LLMAW_MAX_ITERATIONS, default 30):
          run each rule in batch (_execute_rule)
          current = fetch labels
          if llmaw:needs-human in current: stop          (FR-05)
          new = current - seen
          if not new: stop                                (FR-05)
          next_rules = find_next_rules(all_rules, sorted(new))
          if not next_rules: stop                         (FR-05)
          seen = current; batch = matrix(next_rules)
```

## Data Models

### Execution-mode resolution inputs

| Field | Type | Constraints | Description |
|---|---|---|---|
| EXECUTION (env / `inputs.execution` / `vars.LLMAW_EXECUTION`) | str \| empty | `continuous` \| `event-driven` \| empty | Highest-priority override; empty resolves downward |
| `flows.<name>.execution` | str \| null | `continuous` \| `event-driven` | Per-flow setting |
| `defaults.execution` | str \| null | `continuous` \| `event-driven` | Fallback for every flow |
| LLMAW_MAX_ITERATIONS | int | default 30 | Iteration cap for continuous mode |

## API Contracts

### `engine.find_next_rules(rules, new_labels)`

**Inputs**

| Field | Type | Required | Description |
|---|---|---|---|
| rules | list[Rule] | yes | All flattened rules |
| new_labels | list[str] | yes | Labels added since the previous iteration |

**Returns**: the subset of rules that are issue `labeled` rules with an explicit `when.label` matching one of `new_labels`.

### `engine.resolve_dispatch_execution(flows_raw, rules, override)`

**Returns**: `continuous` if `override` is a valid mode, else if any matched rule's flow resolves to continuous, else `event-driven` (or the default when no rules match).

## Sequences

### One continuous iteration

```
iteration begins (batch of rules)
  -> _execute_rule per rule (pre -> agent -> post -> on_outcome)   [FEAT-0002]
  -> fetch current issue labels (gh issue view --json labels)
  -> compute new_labels = current - seen
  -> terminal? (needs-human | no new | no match | cap) -> stop with reason log
  -> else seen = current; batch = matrix(find_next_rules(all_rules, new_labels))
```

## Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Key on issue labels only | Only `when: {event: issues, action: labeled, label: X}` rules chain | PR/comment rules cannot loop; their linked-issue relabel triggers its own dispatch |
| Re-read flows.yml for chaining | `_load_all_rules()` loads the flat rule list fresh | Continuous mode may run after the working tree changed; reads the main-pinned `FLOWS_FILE` |
| Any-continuous-wins | Dispatch is continuous if any matched flow is | Richest behavior wins; mixed matches get the loop |
| PR subjects skip the loop | Run seed once | The chain lives on issues; a PR relabels a linked issue which dispatches separately |

## Risks and Unknowns

1. A long pipeline runs as one job, so a failure mid-chain re-runs the whole job on retry; idempotent label diffs mitigate double-application but skill side effects may not be idempotent.
2. The iteration cap is per-dispatch; very long flows must still fit within the cap (and the job timeout).
3. Re-reading labels via `gh` each iteration adds API calls proportional to chain length.

## Out of Scope

- The per-rule pipeline itself (handled by FEAT-0002).
- The matching that selects seed rules (handled by FEAT-0001).
