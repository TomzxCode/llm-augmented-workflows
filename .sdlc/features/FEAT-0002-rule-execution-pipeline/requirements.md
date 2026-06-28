---
title: "Rule Execution Pipeline"
status: approved
---

# Requirements: Rule Execution Pipeline

## Overview

Each matched rule runs as an ordered pipeline in one pass: pre deterministic (`labels`/`shell`) -> agent (`skill`/`prompt` via opencode) -> post deterministic (`labels`/`shell`) -> `on_outcome` (verdict-to-action).
This feature owns the driver (`run_rule.py`), the deterministic-step applier (`run_steps.py`), the outcome applier (`apply_outcome.py`), and the opencode invocation contract.
It is what actually performs transitions on GitHub (relabel, comment, open/close PR) and how the agent's domain verdict becomes concrete label/close/comment actions.

## Stakeholders

| Stakeholder | Interest |
|---|---|
| Flow author | A predictable, ordered pipeline with token-free deterministic steps bracketing the agent |
| Agent skill author | A clean outcome contract (`$OUTCOME_YAML`: `verdict` + `reason`) that keeps skills label-agnostic |
| GitHub Actions operator | Idempotent label transitions, clear logs, and graceful fallback when an agent emits no verdict |

## Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | Must | The system shall, for each matched rule, run its whole `run` pipeline in order: pre `labels`/`shell`, then the agent (if any), then post `labels`/`shell`, then `on_outcome` (if any). |
| FR-02 | Must | A `labels` step shall support `add`, `remove`, and `target` (`subject` default, or `linked-issue`), and shall be diffed against current labels so add/remove are idempotent and never error on already-present/absent labels. |
| FR-03 | Must | `target: linked-issue` shall parse `#N` (or `closes|fixes|resolves|plan for issue #N`) from the PR title/body and operate on that issue; if none is found it shall skip with a warning. |
| FR-04 | Must | A `shell` step shall run a script via `bash`, resolving the script path against `$LLMAW_TOOLING_ROOT` when set so scripts always run from main, and shall pass the listed argv as positional arguments. |
| FR-05 | Must | An agent step shall run `opencode run --model <id> --dangerously-skip-permissions` with `--command <name>` (skill) or the prompt file's text (prompt), and shall fail the pipeline on a non-zero exit. |
| FR-06 | Must | The system shall reset `$OUTCOME_YAML` (delete if present) before running the agent so each agent starts clean. |
| FR-07 | Must | An `on_outcome` step shall read `$OUTCOME_YAML`, select the action for `outcome.verdict` (falling back to the `_` default), and apply its `labels`/`close`/`comment` to the subject, where a `post_reason: true` action posts the outcome's `reason` instead of the hardcoded `comment`. |
| FR-08 | Must | The `on_outcome` action shall require both `verdict` and `reason`; if either is missing, the system shall resume the opencode session once (`opencode run --continue`) to request a complete outcome before applying the fallback. |
| FR-09 | Must | If no case matches and there is no `_` default, the system shall post a notice comment on the subject that the skill produced no actionable outcome. |
| FR-10 | Must | When posting a comment inside GitHub Actions, the system shall append a workflow-run link footer built from `GITHUB_SERVER_URL` / `GITHUB_REPOSITORY` / `GITHUB_RUN_ID`. |
| FR-11 | Must | GitHub mutations shall use the `gh` CLI with `GH_TOKEN`, and the subject shall be derived from `ISSUE_NUMBER` / `PR_NUMBER`. |
| FR-12 | Should | The system shall fold each rule's output under a `::group::` block in GitHub Actions logs (no-op outside Actions). |

## Non-Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Category | Requirement |
|---|---|---|---|
| NFR-01 | Must | Security | The pipeline shall use only the tokens it is handed (`GH_TOKEN`, the App token); it shall not introduce additional credentials. |
| NFR-02 | Must | Reliability | A failing `shell` step or non-zero agent exit shall fail the job loudly rather than silently advancing. |
| NFR-03 | Should | Observability | The pipeline shall log the rule id, the selected verdict, and label add/remove diffs. |

## Constraints

- At most one agent step and one `on_outcome` per rule (enforced by FEAT-0001).
- Deterministic `labels`/`shell` steps may appear before or after the agent; `on_outcome` must follow the agent and be last.
- `gh` and `opencode` inherit the process environment, so the workflow sets all context env vars on the runner step.

## Acceptance Criteria

Every FR and NFR shall have at least one acceptance criterion.

- [ ] **FR-01**
    - **Given** a rule with a pre `labels`, an agent, a post `labels`, and an `on_outcome`
    - **When** the rule runs
    - **Then** steps execute in that exact order
- [ ] **FR-02**
    - **Given** a subject already labeled `x`
    - **When** a `labels: { add: [x, y], remove: [z] }` step runs
    - **Then** only `y` is added and nothing is removed (idempotent)
- [ ] **FR-03**
    - **Given** a PR titled `Plan for issue #42`
    - **When** a `labels: { add: [plan-approved], target: linked-issue }` step runs
    - **Then** issue `#42` receives `plan-approved`
- [ ] **FR-04**
    - **Given** `$LLMAW_TOOLING_ROOT` set to the main snapshot
    - **When** a `shell: [.github/llmaw/scripts/commit-sdlc.sh, "draft plan"]` step runs
    - **Then** the script runs from the snapshot path with `$1 == "draft plan"`
- [ ] **FR-05**
    - **Given** a `skill: generate-plan` step
    - **When** the agent runs
    - **Then** `opencode run --model <resolved> --dangerously-skip-permissions --command generate-plan` is invoked and a non-zero exit fails the job
- [ ] **FR-07 / FR-08**
    - **Given** a rule with `on_outcome` and an agent that wrote `verdict: approved` but no `reason`
    - **When** the pipeline reaches `on_outcome`
    - **Then** the opencode session is resumed once to request a complete outcome before falling back
- [ ] **FR-09**
    - **Given** a verdict with no matching case and no `_` default
    - **When** `on_outcome` applies
    - **Then** a notice comment is posted on the subject

## Conflicts

None identified yet.

## Open Questions

1. Should multiple agent steps per rule be supported eventually, or is "one agent step; chain via labels" the permanent model? (Currently the latter.)
