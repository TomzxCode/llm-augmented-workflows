---
title: "Flow Configuration and Routing"
status: approved
---

# Requirements: Flow Configuration and Routing

## Overview

Consumers describe their GitHub automation declaratively in a single `.github/llmaw/flows.yml` as event-matched rules grouped into flows.
The routing engine loads that config, flattens every rule across every flow into one ordered list, matches the current GitHub event against each rule's `when` matcher, and emits the matched rules as a GitHub Actions matrix.
This feature is the pure, side-effect-free core of the engine: it defines the config schema, the matching semantics, and the deterministic dispatch decision that the rest of the system executes.

## Stakeholders

| Stakeholder | Interest |
|---|---|
| Flow author | A declarative schema with predictable matching and fast failure on config errors |
| GitHub Actions operator | Deterministic routing that emits a clean matrix and skips cleanly on zero matches |

## Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | Must | The system shall load a YAML config file (`flows.yml`) containing an optional `defaults` block, an optional `labels` block, and a `flows` mapping of named flows to rule lists. |
| FR-02 | Must | The system shall flatten every rule across every flow into a single ordered list, preserving declaration order, and shall treat flow grouping as organizational only (it does not affect routing). |
| FR-03 | Must | Each rule shall declare a unique `id`, a `when` event matcher, and an ordered `run` pipeline of steps. |
| FR-04 | Must | The `when` matcher shall support the ANDed fields `event`, `action`, `label`, `merged`, `branch_prefix`, and `body_contains`, where unspecified fields are wildcards. |
| FR-05 | Must | The system shall match the current GitHub event (event name + payload) against every flattened rule and collect all matches, so that most events match exactly one rule and several matches run in parallel. |
| FR-06 | Must | The system shall emit the matched rules as a JSON Actions matrix plus a `count`, a `has_agent` flag, and the resolved `execution` mode to the workflow outputs. |
| FR-07 | Must | The system shall normalize a rule's `run` to an ordered list, require each step to have exactly one key drawn from the known step kinds, and validate that deterministic steps precede `on_outcome` and that there is at most one agent step and one `on_outcome` per rule. |
| FR-08 | Must | The system shall resolve agent-step settings (model, agents_repository, timeout_minutes) as step override > `defaults` > hardcoded base, and accept both a scalar or a `{name/path/ref, ...overrides}` object for skill/prompt steps. |
| FR-09 | Must | The system shall raise a `ConfigError` and fail fast on any structural problem (missing id, unknown step kind, malformed `when`, bad `on_outcome`, rule with no steps) rather than misroute. |
| FR-10 | Should | The system shall support a manual dry-run that force-runs a single rule by id (`FORCE_RULE_ID`) on `workflow_dispatch`, bypassing event matching. |
| FR-11 | Should | The system shall normalize a `shell` step value as either a plain string (script path) or a list (argv: script + positional args), and a `labels` step `add`/`remove` value as either a string or a list. |

## Non-Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Category | Requirement |
|---|---|---|---|
| NFR-01 | Must | Testability | The routing core shall be free of GitHub/HTTP side effects so it can be unit tested directly. |
| NFR-02 | Must | Portability | The core shall depend only on `pyyaml` and the Python standard library. |
| NFR-03 | Must | Reliability | Routing shall be deterministic for a given config and event, so a config typo fails at the route step instead of misrouting. |

## Constraints

- The config file lives at `.github/llmaw/flows.yml` (overridable via `FLOWS_FILE`) and is read from the tooling snapshot pinned to main.
- Only GitHub events are modeled; there are no non-GitHub triggers.
- The engine runs inside GitHub Actions and reads the event from `GITHUB_EVENT_NAME` / `GITHUB_EVENT_PATH`.

## Acceptance Criteria

Every FR and NFR shall have at least one acceptance criterion.

- [ ] **FR-01**
    - **Given** a valid `flows.yml` with `defaults`, `labels`, and two flows
    - **When** the config is loaded
    - **Then** it parses into a mapping without error
- [ ] **FR-02**
    - **Given** two flows each with multiple rules
    - **When** rules are flattened
    - **Then** the resulting list contains every rule in declaration order regardless of flow grouping
- [ ] **FR-04**
    - **Given** a rule with `when: { event: pull_request, action: closed, merged: true, branch_prefix: plan/ }`
    - **When** a `pull_request` `closed` event arrives for a merged PR on branch `plan/issue-42`
    - **Then** the rule matches
    - **And when** any one field disagrees (wrong action, not merged, wrong prefix)
    - **Then** the rule does not match
- [ ] **FR-05 / FR-06**
    - **Given** the current GitHub event
    - **When** `llmaw route` runs
    - **Then** exactly the matching rules are emitted as a JSON matrix with the correct `count` and `has_agent` flag
- [ ] **FR-07**
    - **Given** a `run` list with two agent steps
    - **When** the rule is parsed
    - **Then** a `ConfigError` is raised complaining that only one agent step is supported
- [ ] **FR-08**
    - **Given** a skill step with `model` override
    - **When** the agent is built
    - **Then** the override wins over `defaults.model` and the hardcoded base
- [ ] **FR-09**
    - **Given** a rule missing an `id`
    - **When** the config is flattened
    - **Then** a `ConfigError` is raised and routing returns exit code 1
- [ ] **FR-10**
    - **Given** a `workflow_dispatch` event with `FORCE_RULE_ID` set
    - **When** `llmaw route` runs
    - **Then** the matrix contains only that rule (no event matching)
- [ ] **NFR-01**
    - **Given** the engine module
    - **When** inspected
    - **Then** it contains no subprocess/network calls and is exercised by pure unit tests

## Conflicts

None identified yet.

## Open Questions

1. Should `when` support OR semantics across multiple values (e.g. multiple labels), or is AND-only sufficient indefinitely? (Currently AND-only.)
