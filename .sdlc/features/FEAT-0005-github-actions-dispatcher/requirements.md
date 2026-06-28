---
title: "GitHub Actions Dispatcher and Consumption"
status: approved
---

# Requirements: GitHub Actions Dispatcher and Consumption

## Overview

The dispatcher (`.github/workflows/dispatch.yml`) is the reusable workflow that hosts the engine inside GitHub Actions.
Consumers add a single wrapper workflow that calls it by ref; the dispatcher mints a GitHub App installation token (so chaining mutations re-trigger workflows), checks out the consumer repo and the engine, pins the llmaw tooling to main, installs opencode and the agents-repository skills, runs `llmaw route` then `llmaw run-rule` over the matched matrix, and exposes ref-pinned versioning for safe org-wide rollout.
This feature is what makes the engine zero-copy and deployable without hosting a service.

## Stakeholders

| Stakeholder | Interest |
|---|---|
| Consumer maintainer | One wrapper file + ref pin, works with only the auto-provided `GITHUB_TOKEN` (free default model) |
| GitHub Actions operator | Per-subject concurrency isolation, reliable opencode install, and traceable app-token attribution |
| Security operator | Least-privilege permissions, supply-chain pinning via `<full-sha>` refs |

## Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | Must | The dispatcher shall be a reusable workflow (`workflow_call`) triggered on the superset of GitHub events: `issues` (opened/labeled/reopened/closed), `pull_request` (closed/labeled/ready_for_review), `issue_comment` (created), `pull_request_review_comment` (created). |
| FR-02 | Must | The dispatcher shall mint a GitHub App installation token via `actions/create-github-app-token@v3` (from `LLMAW_CLIENT_ID` + `LLMAW_APP_PRIVATE_KEY`) and use it for all chaining mutations and checkouts. |
| FR-03 | Must | The dispatcher shall check out the consumer repo on its default branch and check out the engine repo (`framework-repository` / `framework-ref`, default `TomzxCode/llm-augmented-workflows` / `main`) into `.llmaw/`. |
| FR-04 | Must | The dispatcher shall snapshot `.github/llmaw/` from main into `$LLMAW_TOOLING_ROOT` and set `FLOWS_FILE` to that snapshot before any rule runs, so the flow config and scripts always run from main regardless of the working-tree branch. |
| FR-05 | Must | The dispatcher shall run `uv run --project .llmaw llmaw route`, then install opencode (only if any matched rule has an agent) and clone the agents repository (`AGENTS_REPOSITORY`, default `tomzx/agents`) symlinking its `skills/` and `AGENTS.md` into `~/.opencode`. |
| FR-06 | Must | The dispatcher shall run `uv run --project .llmaw llmaw run-rule` over the matched matrix, setting the full context environment (`REPO`, `ISSUE_*`, `PR_*`, `COMMENT_*`, `GH_TOKEN`, `OUTCOME_YAML`, `EXECUTION`, `LLMAW_MAX_ITERATIONS`, `OPENCODE_DISABLE_AUTO_UPDATE`). |
| FR-07 | Must | The dispatcher shall skip the run when `count == 0` (zero matches is a no-op). |
| FR-08 | Must | The dispatcher shall declare `concurrency: { group: llmaw-<subject>, cancel-in-progress: false }` keyed on the issue/PR number so overlapping events queue rather than race. |
| FR-09 | Must | The dispatcher shall declare `permissions: { contents: write, pull-requests: write, issues: write }`. |
| FR-10 | Should | The opencode install shall retry up to a bounded number of attempts with backoff before failing the job. |
| FR-11 | Should | Model and agents-repository shall resolve as workflow input > repo variable (`OPENCODE_MODEL` / `AGENTS_REPOSITORY`) > hardcoded default. |
| FR-12 | Should | The dispatcher shall accept a `rule-id` input for manual dry-run (force-run one rule, skipping event matching). |

## Non-Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Category | Requirement |
|---|---|---|---|
| NFR-01 | Must | Security | Events from the default `GITHUB_TOKEN` never trigger downstream workflows, so all chaining mutations must be attributed to the App token. |
| NFR-02 | Must | Compatibility | The engine must run on `ubuntu-latest` with shallow checkouts (`fetch-depth: 1`) for large repos. |
| NFR-03 | Should | Reliability | The opencode install must be resilient to transient network failures. |

## Constraints

- Requires a GitHub App installed with contents/issues/pull-requests write + metadata read, and repo/org secrets `LLMAW_CLIENT_ID` / `LLMAW_APP_PRIVATE_KEY`.
- The default free model needs only the auto-provided token; non-free models may need a provider secret read by opencode from the environment.
- A moving major tag (`@v1`) and immutable `<full-sha>` pins are supported for versioning.

## Acceptance Criteria

Every FR and NFR shall have at least one acceptance criterion.

- [ ] **FR-01**
    - **Given** the wrapper workflow triggers on the declared events
    - **When** the dispatcher runs
    - **Then** it accepts the `workflow_call` and routes the event
- [ ] **FR-02**
    - **Given** the App secrets are configured
    - **When** the dispatcher starts
    - **Then** an App installation token is minted and used for checkouts and mutations
- [ ] **FR-04**
    - **Given** a rule switches the working tree to `sdlc/issue-42`
    - **When** a `shell` step resolves a script
    - **Then** it resolves from `$LLMAW_TOOLING_ROOT` (main), not the issue branch
- [ ] **FR-05**
    - **Given** a dispatch whose matched rules have no agent
    - **When** routing completes
    - **Then** opencode and the agents repository are not installed
- [ ] **FR-07**
    - **Given** an event that matches zero rules
    - **When** `count == 0`
    - **Then** the run step is skipped
- [ ] **FR-08**
    - **Given** two events for the same issue in quick succession
    - **When** both dispatch
    - **Then** they queue on the per-subject concurrency group (not cancel each other)
- [ ] **NFR-01**
    - **Given** a relabel performed by the dispatcher
    - **When** the label event fires
    - **Then** it is attributed to the App and re-triggers the dispatcher

## Conflicts

None identified yet.

## Open Questions

1. Should the dispatcher support a checkout of the agents repository at a pinned ref (for supply-chain control), or is the default branch sufficient? (Currently clones default branch.)
