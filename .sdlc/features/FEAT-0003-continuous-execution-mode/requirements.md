---
title: "Continuous Execution Mode"
status: approved
---

# Requirements: Continuous Execution Mode

## Overview

Each dispatch runs a matched rule's pipeline and then either stops (`event-driven`, the default, one job per phase) or keeps chaining to the next rule in the same job (`continuous`, one job per pipeline).
Continuous mode advances the flow's label state-machine inside a single job: after each rule's `on_outcome`, it re-reads the issue's labels, finds the rule whose `when.label` matches a newly-added label, runs it, and repeats until a terminal condition.
This dramatically cuts dispatch overhead for long pipelines (the feature SDLC has a dozen phases) while preserving the same rule definitions used by event-driven chaining.

## Stakeholders

| Stakeholder | Interest |
|---|---|
| Flow author | Wanting long pipelines to complete in one job without rewriting rules |
| GitHub Actions operator | Predictable termination and a clear iteration cap |

## Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | Must | The system shall support two execution modes, `event-driven` (default) and `continuous`, resolved as workflow input/repo variable > `flows.<name>.execution` > `defaults.execution` > `event-driven`. |
| FR-02 | Must | In `event-driven` mode, the system shall run each matched rule's pipeline once and end the job (the relabel emits a new event that re-triggers the dispatcher). |
| FR-03 | Must | In `continuous` mode, after the seed rule(s) run, the system shall re-read the issue's labels, compute the labels added since the previous iteration, find the issue-`labeled` rule whose `when.label` is among them, and run it, repeating in the same job. |
| FR-04 | Must | Continuous chaining shall key only on issue `labeled` rules with an explicit `when.label`; PR/comment/merge rules and event-agnostic rules shall never be auto-chained. |
| FR-05 | Must | The continuous loop shall stop when `llmaw:needs-human` is present on the issue, when a rule adds no new label, when the new labels match no rule, or when the iteration cap is reached. |
| FR-06 | Must | The iteration cap shall default to 30 and be overridable via `LLMAW_MAX_ITERATIONS`. |
| FR-07 | Must | Continuous mode shall apply only to issue subjects; PR/comment subjects shall run their seed rule once without looping, and any relabel they cause on a linked issue triggers its own (continuous) dispatch. |
| FR-08 | Must | When resolving a dispatch-level execution mode from multiple matched rules, the run shall be `continuous` if any matched rule's flow is continuous, else `event-driven`; a run with no matched rules is `event-driven`. |

## Non-Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Category | Requirement |
|---|---|---|---|
| NFR-01 | Must | Reliability | The loop must be guaranteed to terminate via the iteration cap even if labels keep churning. |
| NFR-02 | Should | Observability | The loop shall log each iteration, the newly-added labels, and the stop reason. |

## Constraints

- The chain keys on the issue label state-machine only; the label a phase adds must be the label its successor matches (already required by event-driven chaining).
- A rule that opens a PR (e.g. `create-plan`, whose `on_outcome: approved: {}` adds no label) naturally ends the loop; the chain resumes when the PR merges and relabels the linked issue.

## Acceptance Criteria

Every FR and NFR shall have at least one acceptance criterion.

- [ ] **FR-01**
    - **Given** `flows.feature.execution: continuous` and no higher override
    - **When** a feature-flow rule matches
    - **Then** the resolved execution mode is `continuous`
- [ ] **FR-03 / FR-04**
    - **Given** continuous mode and a rule that adds `llmaw:create-requirements`
    - **When** the seed rule's `on_outcome` runs
    - **Then** the loop finds the rule with `when.label: llmaw:create-requirements` and runs it next
- [ ] **FR-05**
    - **Given** continuous mode
    - **When** a rule adds `llmaw:needs-human`
    - **Then** the loop stops after that iteration
- [ ] **FR-06**
    - **Given** `LLMAW_MAX_ITERATIONS=2` and a chain longer than two rules
    - **When** continuous mode runs
    - **Then** the loop stops after the second iteration with a cap warning
- [ ] **FR-07**
    - **Given** continuous mode and a PR subject
    - **When** the seed rule runs
    - **Then** it runs once and does not loop
- [ ] **NFR-01**
    - **Given** rules that add each other's labels forever
    - **When** continuous mode runs
    - **Then** it stops at the iteration cap

## Conflicts

None identified yet.

## Open Questions

1. Should the iteration cap be per-flow rather than per-dispatch? (Currently per-dispatch.)
