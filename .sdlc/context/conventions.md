# Conventions

## Naming

- **Files (Python):** `snake_case.py` (e.g. `run_steps.py`, `apply_outcome.py`, `sync_labels.py`).
- **Files (shell/scripts):** `kebab-case.sh` (e.g. `close-linked-issue.sh`, `ensure-branch.sh`, `commit-sdlc.sh`).
- **Files (docs/config):** `kebab-case.md` / `kebab-case.yml` (e.g. `flows.md`, `flows.yml`, `pr-description-template.md`).
- **Python package:** underscores (`llm_augmented_workflows`); installed as the `llmaw` console script.
- **Variables:** `snake_case` (e.g. `flows_raw`, `to_add`, `base_agents_repo`).
- **Functions / Methods:** `snake_case` (e.g. `flatten_rules`, `compute_label_diff`, `resolve_dispatch_execution`).
- **Classes:** `PascalCase` (e.g. `AgentStep`, `ConfigError`, `When`); value types are frozen dataclasses.
- **Constants:** `UPPER_SNAKE_CASE` (e.g. `DETERMINISTIC_KINDS`, `NEEDS_HUMAN_LABEL`, `DEFAULT_EXECUTION`).
- **Rule ids:** `kebab-case`, unique (e.g. `generate-plan`, `on-plan-merged`, `feat-needs-create`).
- **Flow names:** `kebab-case` or single words (e.g. `triage`, `feature`, `bug`, `review`).
- **Labels:** namespaced with the `llmaw:` prefix; transient triggers use `llmaw:create-<step>` / `llmaw:review-<step>`; durable milestones use `llmaw:<stage>-approved` / `llmaw:shipped`.
- **Branches:** per-issue working branch `sdlc/issue-<N>`; PR head branches use prefixes `plan/`, `impl/`, `fix/`.

## Directory Structure

```
.github/
  workflows/         reusable engine workflows (dispatch, setup-labels, ci)
  wrappers/          consumer-facing callers (the one file repos copy)
  llmaw/
    flows.yml        the flow configuration (per repo)
    scripts/         shell steps (ensure-branch.sh, commit-sdlc.sh)
src/llm_augmented_workflows/   the engine package (installed as the `llmaw` CLI)
  engine.py          pure core: loader, matcher, step resolver
  route.py           llmaw route
  run_rule.py        llmaw run-rule (pipeline driver, continuous mode)
  run_steps.py       llmaw run-steps (deterministic labels/shell)
  apply_outcome.py   llmaw apply-outcome (verdict -> action)
  sync_labels.py     llmaw sync-labels
  cli.py             argparse dispatcher
tests/               pytest unit tests (mirror the module under test)
examples/            example deterministic shell transitions
docs/                authoring guide (flows.md)
```

## Coding Standards

- Target Python 3.14 (`requires-python = ">=3.14"`, ruff `target-version = "py314"`).
- Start every module with a `"""docstring"""` describing its responsibility; CLI modules begin with `#!/usr/bin/env python3`.
- Use `from __future__ import annotations`.
- Use type hints throughout; value types are `@dataclass(frozen=True)`.
- Keep the routing core (`engine.py`) free of GitHub/HTTP side effects so it is unit-testable directly.
- Side-effectful code (`run_steps.py`, `apply_outcome.py`, `sync_labels.py`) shells out to `gh` with `GH_TOKEN` and reuses shared helpers so label/close behavior stays consistent.
- Module-level logger: `log = logging.getLogger(__name__)` (or `"run_rule"`); log the matched rule id, the selected verdict, and label diffs.
- Raise `ConfigError` for structural `flows.yml` problems; fail fast at the route step instead of misrouting.
- ruff rules: `E`, `F`, `I`, `UP`, `B`; line length 100.
- Anti-pattern: do not put GitHub mutations inside `engine.py`; do not couple skill logic to `llmaw:` label names (skills emit domain verdicts).

## Commit Messages

Sentence-case, imperative mood, no conventional-commit prefix, no `Co-authored-by` trailers in the studied history. Examples from `git log`:

- `Bump flow timeout to 60m`
- `Group rule execution in GHA logs`
- `Run tooling from main branch (and not the issue branch)`
- `Add support for continuous execution mode`
- `Refactor rules execution and introduce on_outcome`

## Branching

- `main` is the trunk; CI runs on push to `main` and on pull requests.
- Per-issue working branch for SDLC artifact chains: `sdlc/issue-<N>` (created/checked-out by `ensure-branch.sh`).
- PR head branches are matched by prefix in `when.branch_prefix`: `plan/` (plan PRs), `impl/` (implementation PRs), `fix/` (bug-fix PRs).
- Historical/feature branches seen in the repo: `generic-harness`, `generic-workflows`.

## SDLC Documentation Style

- Write one sentence per line in markdown for easier diff and review.
- Use sentence case for headings.
- Prefer bullet lists and tables over prose paragraphs.
- Reference files as `path:line` where helpful.
- Keep artifacts label-agnostic: skills emit domain verdicts; verdict-to-label mapping lives in `flows.yml`.
