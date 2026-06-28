# Project Overview

## Purpose

LLM Augmented Workflows (`llmaw`) is a config-driven automation engine for GitHub, powered by opencode.
Consumers describe their automation as event-matched rules in a single `.github/llmaw/flows.yml`, and a reusable GitHub Actions dispatcher routes GitHub events (issue labeled, PR merged, comment, ...) to the right opencode agent skill, plus token-free label/shell steps.
It eliminates per-flow workflow files and copied engine boilerplate: each target repo adds exactly one wrapper workflow that calls the central dispatcher by ref, and the engine itself is checked out at runtime rather than copied.

## Key Stakeholders

Named individuals are not recorded in the repository. The stakeholder roles the project serves:

| Stakeholder | Role | Interest |
|---|---|---|
| Consumer maintainer | Adds the wrapper + `flows.yml` to a target repo | Wants zero-copy, ref-pinned automation that works with only the auto-provided `GITHUB_TOKEN` (free default model) |
| Flow author | Writes rules in `flows.yml` and skills in the agents repository | Wants a declarative, debuggable event -> rule -> step model with cheap deterministic transitions |
| Agent skill author | Authors skills in the external agents repository (`tomzx/agents` by default) | Wants skills to stay label-agnostic and reusable across interactive and automated runs |
| GitHub Actions operator | Runs/observes the dispatcher in CI | Wants deterministic routing, fast failure on config errors, and per-subject concurrency isolation |

## Scope

**In scope:**
- A declarative flow configuration schema (`flows.yml`) with event matchers (`when`) and an ordered step pipeline (`run`).
- A pure, unit-tested routing engine that flattens rules across flows and matches GitHub events.
- A rule pipeline driver that runs pre deterministic (`labels`/`shell`) -> agent (`skill`/`prompt`) -> post deterministic -> `on_outcome`, in one pass.
- Two execution modes: `event-driven` (one job per phase) and `continuous` (chain rules in one job until a terminal condition).
- An outcome-driven transition model: agents emit a YAML verdict and `on_outcome` maps it to labels/close/comment.
- Label lifecycle management: auto-create/update declared labels and rename predecessors via `migrate_from`.
- A reusable dispatcher workflow + wrapper consumption model with ref pinning for org-wide rollout.
- opencode agent step execution via the agents repository pattern (clone + symlink skills), with model/timeout resolution.

**Out of scope (per `PLAN.md`):**
- Non-GitHub triggers (Slack, webhooks). The event model is GitHub only.
- A GitHub App / webhook service. Reusable workflows plus ref pinning cover rollout without hosting.
- A UI or visual flow editor.
- Persistent state machine storage. State lives in GitHub (labels, PRs, issues); the framework is stateless.
- Automatic rollback of agent actions beyond what the agent itself does.
- Cross-repository flows.

## Key Constraints

- **GitHub Actions only.** The dispatcher is a reusable workflow; there is no hosted service.
- **Stateless engine.** All state lives in GitHub (labels, issues, PRs). Per-issue working branches (`sdlc/issue-<N>`) are the cross-run persistence for `.sdlc/` artifact chains.
- **opencode as the agent runner.** Agent steps invoke `opencode run --command <skill>` (or a local prompt); skills come from the configured agents repository.
- **Default credential is the auto-provided `GITHUB_TOKEN`.** Non-free models may need a provider secret; the default free model needs none.
- **Anti-recursion token.** Chaining mutations (labels, PR create/merge, comments, git push) must be attributed to a GitHub App installation token, because events produced by the default `GITHUB_TOKEN` never trigger downstream workflows.
- **Python >= 3.14.** Runtime dependency is `pyyaml`; tooling is `uv` + `hatchling` + `pytest` + `ruff`.
- **Tooling pinned to main.** The dispatcher snapshots `.github/llmaw/` from `main` into `$LLMAW_TOOLING_ROOT` before any rule switches the working tree to the per-issue branch, so flow fixes apply to in-flight issues immediately.
