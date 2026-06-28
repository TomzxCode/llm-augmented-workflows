---
title: "GitHub Actions Dispatcher and Consumption"
status: approved
---

# Specification: GitHub Actions Dispatcher and Consumption

## Overview

The dispatcher is `.github/workflows/dispatch.yml`, a reusable workflow (`workflow_call` + `workflow_dispatch`) that hosts the engine.
A consumer adds one wrapper workflow under `.github/workflows/` that calls `TomzxCode/llm-augmented-workflows/.github/workflows/dispatch.yml@<ref>` with `secrets: inherit`.
The dispatcher handles token minting, checkouts, tooling pinning, opencode + skills installation, routing, and the matrix run.

## Architecture

```
consumer .github/workflows/llm-workflows.yml  (uses: .../dispatch.yml@<ref>, secrets: inherit)
   |
   v
dispatch.yml
  job: dispatch (runs-on ubuntu-latest)
    1. actions/create-github-app-token@v3     -> app token (LLMAW_CLIENT_ID + LLMAW_APP_PRIVATE_KEY)
    2. checkout consumer repo (default branch, token=app token)
    3. checkout engine -> .llmaw/ (framework-repository/framework-ref)
    4. snapshot .github/llmaw -> $LLMAW_TOOLING_ROOT ; set FLOWS_FILE
    5. setup-uv (working-directory .llmaw)
    6. llmaw route  -> matched matrix + has_agent + execution      [FEAT-0001]
    7. if has_agent: install opencode (bounded retries) ; clone AGENTS_REPOSITORY ; symlink skills + AGENTS.md
    8. if count != 0: llmaw run-rule (full context env)           [FEAT-0002 / FEAT-0003]
```

## Data Models

### Dispatcher inputs (`workflow_call` / `workflow_dispatch`)

| Field | Type | Default | Description |
|---|---|---|---|
| model | string | `opencode/deepseek-v4-flash-free` | opencode model id |
| agents-repository | string | `tomzx/agents` | Skills repo (`owner/repo`) |
| framework-repository | string | `TomzxCode/llm-augmented-workflows` | Engine repo |
| framework-ref | string | `main` | Engine ref |
| execution | string | `""` | Forced execution mode |
| rule-id | string | - | Dry-run: force-run one rule |

### Secrets / variables

| Name | Kind | Description |
|---|---|---|
| LLMAW_APP_PRIVATE_KEY | secret | GitHub App PEM key |
| LLMAW_CLIENT_ID | variable | GitHub App client id |
| OPENCODE_MODEL | variable | Model id override |
| AGENTS_REPOSITORY | variable | Skills repo override |
| LLMAW_EXECUTION | variable | Execution mode override |
| LLMAW_MAX_ITERATIONS | variable | Continuous cap (default 30) |

## API Contracts

No HTTP API. The contract is the reusable-workflow `uses:` ref and the inputs/secrets above.

### Consumer wrapper (the only per-repo boilerplate)

```yaml
uses: TomzxCode/llm-augmented-workflows/.github/workflows/dispatch.yml@<ref>
secrets: inherit
```

## Sequences

### Tooling pin (run before any rule)

```
RUNNER_TEMP/llmaw-tooling <- copy .github/llmaw from the checked-out consumer main
GITHUB_ENV: LLMAW_TOOLING_ROOT=<that>, FLOWS_FILE=<that>/.github/llmaw/flows.yml
-> shell steps and flows.yml re-reads resolve from here, not the issue branch
```

### Anti-recursion token flow

```
create-github-app-token -> App installation token
-> used for: checkout (token:), gh mutations (GH_TOKEN), git push
-> App-attributed events DO trigger downstream workflows -> label state-machine advances
```

## Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Reusable workflow over a service | `workflow_call` + ref pinning | No hosting; avoids deprecated "required workflows" |
| App token for chaining | `actions/create-github-app-token@v3` | Default `GITHUB_TOKEN` events don't re-trigger workflows (anti-recursion) |
| Tooling pinned to main | Snapshot before branch switch | Flow/script fixes apply to in-flight issues immediately; skills still edit branch content |
| Conditional opencode install | Only when `has_agent == 'true'` | Token-free rules skip the install entirely |
| Per-subject concurrency | `cancel-in-progress: false` | Overlapping events queue, preventing a relabel loop from canceling an in-flight run |

## Risks and Unknowns

1. Requires a configured GitHub App and secrets; misconfiguration fails the App-token step loudly.
2. The agents repository is cloned at its default branch (no ref pin), which is a supply-chain consideration.
3. The opencode install depends on `https://opencode.ai/install` availability; the bounded retry mitigates transient failures.

## Out of Scope

- The routing engine and matrix generation (handled by FEAT-0001).
- The rule pipeline and execution modes (handled by FEAT-0002 and FEAT-0003).
- Label reconciliation (handled by FEAT-0004); the separate `setup-labels.yml` workflow reuses the same engine-checkout pattern.
