# Architecture

## System Overview

The engine is a stateless Python package (`llmaw` CLI) that a reusable GitHub Actions workflow checks out and runs. There is no long-running service. GitHub events enter via the dispatcher; matching rules run as a matrix of isolated jobs; and each job drives a rule's whole pipeline before terminating.

```
GitHub event (issue/PR/comment)
   |
   v
.github/workflows/dispatch.yml   (reusable; mints App token, anti-recursion)
   |-- checkout repo (main) + engine into .llmaw/
   |-- pin .github/llmaw/ -> $LLMAW_TOOLING_ROOT (runs from main)
   |-- uv run --project .llmaw llmaw route
   |        -> reads flows.yml, matches event -> JSON matrix + execution mode
   |
   +-- (per matched rule) Run matched rules:
          uv run --project .llmaw llmaw run-rule
            |
            v
          src/llm_augmented_workflows/run_rule.py  (one pipeline per rule)
            pre labels/shell  (run_steps.py, gh CLI, token-free)
            -> agent          (opencode run --command <skill>, agents repo)
            -> post labels/shell
            -> on_outcome     (apply_outcome.py: verdict -> labels/close/comment)
            |
            v  (continuous mode only: re-read issue labels, find next rule, repeat)
          agent acts on GitHub (relabel, comment, open/merge PR) -> emits new events
```

## Key Components

| Component | Responsibility | Technology |
|---|---|---|
| `engine.py` | Pure core: load `flows.yml`, flatten rules across flows, match events (`when`), normalize `run` steps, validate `on_outcome`, compute label diffs, resolve execution mode | Python, pyyaml, dataclasses |
| `route.py` (`llmaw route`) | Match the current GitHub event to rules and emit the Actions matrix (`matched`, `count`, `has_agent`, `execution`) to `$GITHUB_OUTPUT` | Python, GitHub Actions runtime env |
| `run_rule.py` (`llmaw run-rule`) | Drive a matched rule's whole pipeline (pre -> agent -> post -> on_outcome); continuous-mode chaining | Python, subprocess (`opencode`, `gh`) |
| `run_steps.py` (`llmaw run-steps`) | Apply deterministic `labels`/`shell` steps via the `gh` CLI; resolve scripts against `$LLMAW_TOOLING_ROOT`; find linked issues | Python, `gh` CLI |
| `apply_outcome.py` (`llmaw apply-outcome`) | Read `$OUTCOME_YAML`, select the action for the agent's verdict (or `_` fallback), apply labels/close/comment with `post_reason` override | Python, pyyaml, `gh` CLI |
| `sync_labels.py` (`llmaw sync-labels`) | Create/update declared labels; rename `migrate_from` predecessors preserving issue history; report conflicts | Python, `gh` CLI |
| `cli.py` | argparse dispatcher installed as the `llmaw` console script | Python |
| `.github/workflows/dispatch.yml` | Reusable dispatcher: App token, checkouts, tooling pin, opencode + skills install, matrix run | GitHub Actions |
| `.github/workflows/setup-labels.yml` | Reconciles the `labels:` block with the repo | GitHub Actions |
| `.github/workflows/ci.yml` | Lint (`ruff`) + test (`pytest`) the engine | GitHub Actions |
| `.github/llmaw/flows.yml` | Declarative flow config (this repo's own SDLC flows); the single source of truth for routing | YAML |
| `.github/llmaw/scripts/` | `ensure-branch.sh` (checkout/create `sdlc/issue-<N>`) and `commit-sdlc.sh` (commit + push `.sdlc/`) run as `shell` steps | Bash |
| `docs/flows.md` | Authoring guide + recipes for `flows.yml` | Markdown |
| `examples/` | Example deterministic shell transitions (e.g. `close-linked-issue.sh`) | Bash |

## Data Flow

1. A GitHub event fires. The wrapper workflow calls `TomzxCode/llm-augmented-workflows/.github/workflows/dispatch.yml@<ref>`.
2. `dispatch.yml` mints a GitHub App installation token (so chaining mutations re-trigger workflows), checks out the consumer repo (default branch) and the engine into `.llmaw/`, and snapshots `.github/llmaw/` from main into `$LLMAW_TOOLING_ROOT`.
3. `llmaw route` loads `$FLOWS_FILE`, flattens every rule across every flow, matches the event against each rule's `when`, and writes the matched rule matrix + resolved execution mode to `$GITHUB_OUTPUT` (and `$MATCHED_FILE`).
4. If any matched rule has an agent step, opencode is installed and the agents repository is cloned with `skills/` and `AGENTS.md` symlinked into `~/.opencode`.
5. `llmaw run-rule` runs each matched rule's pipeline: pre `labels`/`shell` -> agent (`opencode run --command <skill>`) -> post `labels`/`shell` -> `on_outcome`. Deterministic steps use `gh` with the App token; the agent reads context from environment variables (`REPO`, `ISSUE_NUMBER`, `PR_TITLE`, ...).
6. The agent (or `on_outcome`) mutates GitHub (relabel, comment, open/close PR). Those mutations emit new events, which re-enter the dispatcher.
7. In `continuous` mode, step 5 repeats in the same job: the engine re-reads the issue's labels, finds the rule whose `when.label` matches a newly-added label, runs it, and loops until `llmaw:needs-human`, no new label, no matching rule, or the iteration cap.

## Infrastructure

- **Hosting:** none. The engine runs inside GitHub Actions reusable workflows.
- **CI:** `.github/workflows/ci.yml` lints with `ruff` and tests with `pytest` on push to `main` and on pull requests.
- **Distribution:** source distribution via the `llmaw` console script entry point in `pyproject.toml`; consumers never copy the engine (checked out at runtime into `.llmaw/`).
- **Versioning:** git tags (`v1`, `v1.2`, `v1.2.3`) plus a moving major tag; consumers pin `<ref>` in the wrapper (`@main`, `@v1`, or `@<full-sha>`).
- **Observability:** GitHub Actions logs only. `run_rule.py` folds each rule under a `::group::` block; `route` logs matched rule ids; `apply_outcome` logs the selected verdict. No metrics/tracing backend.
- **Authentication:** GitHub App installation token for chaining mutations (anti-recursion); the auto-provided `GITHUB_TOKEN` suffices for the default free model and for `setup-labels`.

## Architecture Decisions

Key decisions are documented in `PLAN.md` (the design rationale). Formal ADRs are not yet recorded under `.sdlc/knowledge/decisions/`. Highlights:

- **Stateless engine, GitHub is the state store.** Labels/issues/PRs encode flow state; the per-issue branch `sdlc/issue-<N>` carries `.sdlc/` artifact chains across runs.
- **Reusable workflow + ref pinning over a hosted service.** Avoids hosting and the deprecated "required workflows" feature.
- **Outcome-driven transitions.** Skills emit a domain verdict to `$OUTCOME_YAML`; the verdict-to-label mapping lives in `flows.yml` so skills stay label-agnostic and reusable.
- **Two label families:** transient triggers (`create-<step>`/`review-<step>`, consumed on entry, re-addable to drive revise loops) and durable milestones (`*-approved`, `shipped`, accumulate, never re-added).
- **Tooling pinned to main** so flow fixes land for in-flight issues immediately, while skills still edit per-issue branch content.
