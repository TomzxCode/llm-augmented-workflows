# Design Plan: Generalized LLM-Augmented Workflow Engine

## Goal

Turn this repository from a single hardcoded flow (issue, plan, implement) into a general engine where any number of flows can be defined declaratively.

A flow is a graph of event-driven steps. Each step either runs an agent (an opencode skill or prompt) or a deterministic shell/label command. Agents perform state transitions themselves by acting on GitHub (add or remove labels, comment, open or close a PR, close the issue). The framework only routes events to the right agent.

## Current State (post-opencode rebase)

The repository already runs on opencode, not Claude Code. Each workflow today:
- Installs opencode with `curl -fsSL https://opencode.ai/install | bash`.
- Clones a configurable **agents repository** (default `tomzx/agents`) and symlinks its `skills/` into `~/.opencode/skills` and its `AGENTS.md` into `~/.config/opencode/AGENTS.md`.
- Runs `opencode run --model "$MODEL" --dangerously-skip-permissions --command <skill>`.
- Resolves `model` (default `opencode/deepseek-v4-flash-free`) and `agents-repository` (default `tomzx/agents`) as workflow input, then repo variable (`OPENCODE_MODEL`, `AGENTS_REPOSITORY`), then hardcoded default.
- Authenticates with the auto-provided `GITHUB_TOKEN` only. No `ANTHROPIC_*` secrets, no `id-token: write`.

Files are `plan.yml`, `implement.yml`, `review.yml`, `plan-merged.yml`, `setup-labels.yml` plus matching wrappers that call `TomzxCode/llm-augmented-workflows/.github/workflows/<name>.yml@main`. The local `.agents/commands/*.md` are vestigial: skills now come from the external agents repository. `.claude` and `CLAUDE.md` are symlinks to `.agents` and `AGENTS.md`.

This plan generalizes that base without changing the execution engine.

## Mental Model

```
GitHub event (issue labeled, PR merged, comment, ...)
   |
   v
[dispatcher workflow] reads flows.yml, finds matching rule(s)
   |
   v
for each matched rule: run deterministic steps (labels/shell), then the agent step
   |
   v
agent reads context, does work, performs transitions as side effects
   |
   v
those transitions emit new GitHub events, which re-enter the loop
```

Terminal outcomes emerge naturally: an agent closes the issue (will not fix), or a PR is merged and an `on-merge` rule closes the linked issue.

## Flow Configuration

Single source of truth: `.github/flows.yml`.

### Schema

```yaml
# Optional defaults applied to every agent step unless overridden.
defaults:
  model: opencode/deepseek-v4-flash-free   # opencode model id (provider/model)
  agents_repository: tomzx/agents          # repo providing skills, cloned at runtime
  timeout_minutes: 30
  permissions: skip                        # maps to opencode --dangerously-skip-permissions

# Labels the setup-labels workflow will create automatically.
labels:
  - name: feature-request
    description: Triaged feature request
    color: 0E8A16
  - name: bug
    description: Bug report
    color: D73A4A

# Flows group related rules. Grouping is organizational, it does not affect routing.
flows:
  feature-request:
    description: Triage and deliver feature requests.
    rules:
      - id: triage-feature
        when:
          event: issues
          action: labeled
          label: feature-request
        run:
          # Deterministic prep, runs first, costs no tokens.
          - labels:
              remove: [feature-request]
              add: [triaged]
          # Then the agent runs and decides the next transition itself
          # (needs-info, ready-to-plan, wontfix + close, etc.).

          - skill: triage-feature-request

      - id: generate-plan
        when:
          event: issues
          action: labeled
          label: ready-to-plan
        run:
          - skill: generate-plan

      - id: respond-to-plan-review
        when:
          event: pull_request_review_comment
          action: created
          branch_prefix: plan/
        run:
          - skill: review-plan-comment

      - id: on-plan-merged
        when:
          event: pull_request
          action: closed
          merged: true
          branch_prefix: plan/
        run:
          # Pure deterministic relabel, no agent involved.
          - labels:
              add: [plan-approved]

      - id: implement
        when:
          event: issues
          action: labeled
          label: plan-approved
        run:
          - skill: implement-plan

      - id: close-on-impl-merged
        when:
          event: pull_request
          action: closed
          merged: true
          branch_prefix: impl/
        run:
          - shell: examples/close-linked-issue.sh

  bug-fix:
    description: Triage and fix bugs.
    rules:
      - id: triage-bug
        when:
          event: issues
          action: labeled
          label: bug
        run:
          - labels:
              remove: [bug]
              add: [needs-triage]
          - skill: triage-bug

      - id: implement-fix
        when:
          event: issues
          action: labeled
          label: bug-approved
        run:
          - skill: implement-fix
```

### Rule fields

| Field | Meaning |
|-------|---------|
| `id` | Unique rule id, used in logs and the matrix. |
| `when` | Event matcher. All fields are ANDed, unspecified fields are wildcards. |
| `run` | Ordered list of steps to execute when the rule matches. A single object is treated as a one-element list. |

### `when` matchers

| Field | For events | Meaning |
|-------|------------|---------|
| `event` | all | GitHub event name (`issues`, `pull_request`, `issue_comment`, `pull_request_review_comment`). |
| `action` | all | Event action (`opened`, `labeled`, `closed`, `created`). |
| `label` | issues, pull_request | Label name that must match on a `labeled` event. |
| `merged` | pull_request | Require `merged` true or false on a `closed` event. |
| `branch_prefix` | pull_request | Match the PR head branch by prefix. |
| `body_contains` | issues, pull_request | Match the body substring (legacy plan PR detection). |

### Steps

`run` is an ordered list. Each item is one step, discriminated by its key.

| Step key | What it does |
|----------|--------------|
| `labels` | Adds and/or removes labels on the issue or PR. Deterministic, no LLM, no tokens. |
| `shell` | Runs a shell script. Deterministic, no LLM. |
| `skill` | Runs an opencode command (`opencode run --command <name>`) from the configured agents repository. Costs tokens. |
| `prompt` | Runs opencode with a local prompt file's contents. Costs tokens. Use for repo-specific logic that is not a shared skill. |

The `labels` step is the easy, token-free way to transition state:

```yaml
- labels:
    add: [ready-to-plan]       # optional, list or single string
    remove: [feature-request]   # optional, list or single string
    target: subject             # subject (default) | linked-issue
```

`target: linked-issue` parses `#N` (or `closes|fixes|resolves|plan for issue #N`) from the PR title/body and labels that issue. The orchestrator diffs against the item's current labels, so `add` and `remove` are idempotent and never error on labels that are already present or absent.

Agent steps accept overrides (`model`, `agents_repository`, `timeout_minutes`, `permissions`) that default to the top-level `defaults`. `permissions: skip` maps to opencode's `--dangerously-skip-permissions`, which is what the current workflows already pass.

**Execution order.** Steps run sequentially in listed order. Deterministic steps (`labels`, `shell`) run first, in their relative order, via a single orchestrator script. Then the agent step (`skill` or `prompt`) runs via `opencode run`. Transitions that should happen after the agent are performed by the agent itself, this is the agent-driven model. v1 supports one agent step per rule, chain more by emitting a label and matching it with another rule.

## Matching Semantics

- The router flattens all rules across all flows into one list.
- On an event it evaluates every rule and collects all matches.
- Matched rules run as a GitHub Actions matrix, one isolated job per rule.
- Most events match exactly one rule. If several match, they run in parallel.
- Rule `when` fields are ANDed. Unspecified fields are wildcards.

## Context Variables Contract

The dispatcher exposes context to every agent and shell step as environment variables, mirroring what the current workflows already pass to `opencode run`.

| Variable | Present when | Example |
|----------|--------------|---------|
| `REPO` | always | `owner/repo` |
| `EVENT_NAME` | always | `issues` |
| `EVENT_ACTION` | always | `labeled` |
| `ISSUE_NUMBER` | issues, issue comments | `42` |
| `ISSUE_TITLE` | issues | `Add dark mode` |
| `ISSUE_BODY` | issues | issue body text |
| `ISSUE_LABELS` | issues | comma-separated list |
| `LABEL` | labeled events | the label that was added |
| `PR_NUMBER` | pull request events | `7` |
| `PR_BRANCH` | pull request events | `plan/issue-42-...` |
| `PR_TITLE` | pull request events | `Plan for issue #42` |
| `PR_MERGED` | pull request closed | `true` |
| `COMMENT_AUTHOR` | comment events | `octocat` |
| `COMMENT_BODY` | comment events | comment text |
| `COMMENT_TYPE` | comment events | `inline` or `general` |
| `GH_TOKEN` | always | the auto-provided `GITHUB_TOKEN` |
| `OPENCODE_DISABLE_AUTO_UPDATE` | always | `1` |

Skills read these the same way the current `generate-plan` / `implement-plan` skills read `REPO` and `ISSUE_NUMBER` today.

## Dispatcher Architecture

Two reusable pieces plus one wrapper.

### `.github/workflows/dispatch.yml` (reusable)

- Triggers on the superset of events:
  - `issues: [opened, labeled, reopened, closed]`
  - `pull_request: [closed, labeled, ready_for_review]`
  - `issue_comment: [created]`
  - `pull_request_review_comment: [created]`
- Accepts `model`, `agents-repository`, `framework-repository`, and `framework-ref` inputs with the same input, then vars (`OPENCODE_MODEL`, `AGENTS_REPOSITORY`), then default resolution used today.
- Job `route`:
  - Checks out the repo (to read `flows.yml`) and the engine repo into `.llmaw/` (by `framework-repository`/`framework-ref`).
  - Runs `uv run --project .llmaw llmaw route` (Python package, depends on `pyyaml`).
  - The command loads `.github/flows.yml`, evaluates the current event against every rule, and writes a JSON array of matched rules to `$GITHUB_OUTPUT`.
  - Outputs `matched` (JSON list), `count`.
- Job `run-rule` (`needs: route`, matrix over `fromJson(needs.route.outputs.matched)`):
  - Checks out the repo (default branch, shallowly) and the engine repo into `.llmaw/`.
  - Runs `uv run --project .llmaw llmaw run-steps` to execute all deterministic steps (`labels`, `shell`) in order against the current issue or PR, using `GH_TOKEN`.
  - If the rule has an agent step:
    - Installs opencode: `curl -fsSL https://opencode.ai/install | bash`.
    - Clones the configured `agents_repository` and symlinks `skills/` and `AGENTS.md` into `~/.opencode`, exactly as the current workflows do.
    - Runs `opencode run --model "$MODEL" --dangerously-skip-permissions --command <skill>` (skill step) or with the local prompt file contents (prompt step), passing the context env vars.
- Concurrency group per subject (issue or PR id) so overlapping events queue rather than race.

### `llm_augmented_workflows.engine` + `route`

- Loads YAML, flattens rules, matches against `GITHUB_EVENT_NAME`, `GITHUB_EVENT_PATH` payload, and GitHub context.
- Normalizes `run` to a list and validates that each step has exactly one key, deterministic steps precede the agent step, and there is at most one agent step.
- Pure and side-effect free aside from emitting outputs, so it is easy to unit test.
- Unit tests live in `tests/test_engine.py` and run in CI.

### `llm_augmented_workflows.run_steps`

- Receives a rule's deterministic steps and the subject (issue or PR number).
- Applies `labels` steps by diffing against current labels (idempotent), and runs `shell` steps in order.
- Uses `GH_TOKEN`, no opencode, no tokens. Errors on a shell step fail the job loudly.

## Consumption & Versioning

Each target repo adds exactly one wrapper workflow that calls the central reusable dispatcher by ref. The engine itself never needs to be copied.

```yaml
# .github/workflows/llm-workflows.yml  (the only boilerplate file per repo)
name: LLM Workflows
on:
  issues:
    types: [opened, labeled, reopened, closed]
  pull_request:
    types: [closed, labeled, ready_for_review]
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]
permissions:
  contents: write
  pull-requests: write
  issues: write
concurrency:
  group: llmaw-${{ github.event.issue.number || github.event.pull_request.number || github.run_id }}
  cancel-in-progress: false
jobs:
  dispatch:
    uses: TomzxCode/llm-augmented-workflows/.github/workflows/dispatch.yml@<ref>
    secrets: inherit
```

The `<ref>` controls versioning:

| Ref | Meaning | Use when |
|-----|---------|----------|
| `@main` | Latest, moving | Experimenting or fast-moving internal orgs. |
| `@v1` | Latest within a major tag | Recommended default, gets fixes without breaking changes. |
| `@<full-sha>` | Immutable pin | Supply-chain safety for production repos. |

Releases are cut as git tags (`v1`, `v1.2`, `v1.2.3`) plus a moving major tag. The wrapper is identical across repos, so org rollout is a bulk commit of three files into each repo: the wrapper above, `.github/flows.yml`, and any local `.agents/commands/*.md` prompt files it references. Skills themselves are not copied, they come from the shared, versioned `agents_repository`. Model and agents-repository config reach the dispatcher through the wrapper inputs or repo/org variables, and the auto-provided `GITHUB_TOKEN` is the only credential needed for the default free model.

This keeps the opencode architecture, hosts no service, and avoids the now-deprecated "required workflows" feature entirely.

## Generalizing setup-labels

`.github/workflows/setup-labels.yml` reads the `labels:` block of `.github/flows.yml` and creates or updates each label by running `llmaw sync-labels` from the checked-out engine. Users add a label to config and it appears on next run, no more hardcoded list.

## File Layout

```
.github/
  workflows/
    dispatch.yml                  # generic reusable dispatcher (replaces plan/implement/review/plan-merged)
    setup-labels.yml              # reads labels from flows.yml
    ci.yml                        # lints + tests the package
  wrappers/
    dispatch.yml                  # consumer-facing caller (the one file repos copy)
    setup-labels.yml              # consumer-facing caller
  flows.yml                       # the flow configuration (per repo)
  pr-description-template.md      # kept, used by the implement-plan skill
src/llm_augmented_workflows/      # the engine, installed as the `llmaw` CLI
  engine.py                       # loader, matcher, step resolver (pure, unit-tested)
  route.py                        # event to rule matcher (llmaw route)
  run_steps.py                    # executes a rule's deterministic steps (llmaw run-steps)
  sync_labels.py                  # creates/updates labels from flows.yml (llmaw sync-labels)
  cli.py                          # argparse dispatcher
tests/
  test_engine.py                  # unit tests for the matcher/engine
examples/
  close-linked-issue.sh           # example deterministic transition
docs/
  flows.md                        # authoring guide with copy-paste examples
pyproject.toml                    # package + tooling (hatchling, uv, pytest, ruff)
.python-version                   # 3.14
PLAN.md                           # this file
README.md                         # rewritten around the engine
```

The dispatcher checks this repository out into `.llmaw/` on the worker (via `framework-repository` / `framework-ref` inputs, default `TomzxCode/llm-augmented-workflows` / `main`) and runs `uv run --project .llmaw llmaw ...`, so consumers never copy the engine. Skills referenced by `run.skill` (e.g. `generate-plan`, `implement-plan`, `review-plan-comment`) live in the external agents repository (`tomzx/agents` by default).

## Migration Mapping (current to new)

| Current file | Becomes |
|--------------|---------|
| `plan.yml` | rule `generate-plan` in `feature-request` flow |
| `review.yml` | rule `respond-to-plan-review` |
| `plan-merged.yml` (JS label step) | rule `on-plan-merged` with a `labels` step |
| `implement.yml` | rule `implement` |
| `plan-merged.yml` (JS branch/title detection) | matcher `branch_prefix: plan/` in the router |
| `setup-labels.yml` hardcoded labels | `labels:` block in `flows.yml` |
| Per-workflow `env.TRIGGER_LABEL` / `APPROVAL_LABEL` | `when:` fields per rule |
| Per-workflow opencode install + agents clone | one shared block in `dispatch.yml` |
| Per-workflow `opencode run --command <skill>` | the rule's `skill` step, run by the dispatcher |
| Per-workflow `check-labels` JS | the router's `when` matchers |
| Vestigial `.agents/commands/*.md` | deleted, skills already come from the agents repo |

The agents-repository pattern, the model/agents-repository resolution order, and `--dangerously-skip-permissions` all carry over unchanged. Only the per-flow boilerplate collapses into config.

The old `plan.yml`, `implement.yml`, `review.yml`, `plan-merged.yml` workflows and their wrappers are deleted once `dispatch.yml` covers their events.

## Concurrency and Edge Cases

- `concurrency: { group: dispatch-${{ github.event.issue.number || github.event.pull_request.number }}, cancel-in-progress: false }` so a fast relabel loop cannot cancel an in-flight agent run.
- Zero matches is a normal no-op, the `run-rule` job is skipped via `if: count > 0`.
- Large repos stay on `fetch-depth: 1`.
- The router is deterministic and tested, so a config typo fails the route job fast instead of misrouting.
- `labels` and `shell` steps give cheap, token-free transitions (relabel, close linked issue). Reserve `skill`/`prompt` for work that actually needs the model.
- Non-free models may require a provider API key, passed through as a repo/org secret that opencode reads from the environment; the default free model needs none.

## Implementation Phases

1. **Engine package.** Build `src/llm_augmented_workflows/` (`engine`, `route`, `run_steps`, `sync_labels`, `cli`) with full coverage of the matchers (event, action, label, branch_prefix, merged, body_contains), the defaults merge, `run` list normalization, and the `labels` diff logic, plus the `llmaw` console script. Unit tests in `tests/` run in CI.
2. **Dispatcher workflow.** Add `dispatch.yml` wiring the `route` job to a `run-rule` matrix that calls `run_steps.py` then installs opencode, clones the agents repo, and runs `opencode run`. Verify end to end with a throwaway rule on a test repo or a `workflow_dispatch` dry-run path.
3. **Migrate the plan flow.** Port the four existing workflows into `flows.yml` rules, using a `labels` step for the deterministic relabel. Keep behavior identical, including model and agents-repository resolution.
4. **Generalize setup-labels.** Port to read the `labels:` block.
5. **Add example flows.** Author `triage-feature-request`, `triage-bug`, and `implement-fix` skills in the agents repository as reference flows that show the go/no-go and PR-outcome patterns.
6. **Docs.** Rewrite `README.md`, add `docs/flows.md` with a recipe cookbook.
7. **Cleanup.** Delete the old `plan.yml`/`implement.yml`/`review.yml`/`plan-merged.yml` workflows and wrappers, and the vestigial `.agents/commands/*.md`, after parity is confirmed.

## Explicitly Out of Scope

- Non-GitHub triggers (Slack, webhooks). The event model is GitHub only for now.
- A GitHub App / webhook service. Reusable workflows plus ref pinning cover org rollout without hosting.
- A UI or visual flow editor.
- Persistent state machine storage. State lives in GitHub (labels, PRs, issues), the framework is stateless.
- Automatic rollback of agent actions beyond what the agent itself does.
- Cross-repository flows.
