# LLM Augmented Workflows

A config-driven automation engine for GitHub, powered by opencode. Describe your flows in one `flows.yml` file; the dispatcher routes GitHub events to the right agent skills (and deterministic label/shell steps). No per-flow workflow files, no copied boilerplate.

## How it works

```
GitHub event (issue labeled, PR merged, comment, ...)
   |
   v
dispatch.yml  reads flows.yml  ->  route.py matches rule(s)
   |
   v
per matched rule: deterministic steps (labels/shell), then opencode skill
   |
   v
the agent acts on GitHub (relabel, comment, open PR, close) -> emits new events
```

State lives in GitHub (labels, PRs, issues). The engine is stateless. Terminal outcomes emerge naturally: an agent closes an issue (won't fix), or a PR merges and an `on-merge` rule closes the linked issue.

## Features

- **One config file** (`.github/flows.yml`) defines every flow as event-matched rules.
- **Ordered steps** per rule: `labels`, `shell` (deterministic, token-free) and `skill`, `prompt` (opencode agents).
- **Deterministic transitions** like relabeling cost zero tokens.
- **opencode skills** are sourced from a configurable agents repository (default `tomzx/agents`).
- **Reusable workflow** with ref pinning for safe org-wide rollout.

## Quick start

1. Add one wrapper workflow to your repo, pointing at this dispatcher by ref:

   `.github/workflows/llm-workflows.yml`
   ```yaml
   name: LLM Workflows
   on:
     issues: { types: [opened, labeled, reopened, closed] }
     pull_request: { types: [closed, labeled, ready_for_review] }
     issue_comment: { types: [created] }
     pull_request_review_comment: { types: [created] }
   permissions:
     contents: write
     pull-requests: write
     issues: write
   jobs:
     dispatch:
       uses: TomzxCode/llm-augmented-workflows/.github/workflows/dispatch.yml@<ref>
       secrets: inherit
   ```

2. Add `.github/flows.yml` describing your flows (see [`docs/flows.md`](docs/flows.md) and the example in this repo).

3. (Optional) Set repo/org variables to override the defaults:
   - `OPENCODE_MODEL` - opencode model id (default `opencode/deepseek-v4-flash-free`)
   - `AGENTS_REPOSITORY` - skills repo as `owner/repo` (default `tomzx/agents`)

4. Create the labels declared under `labels:` by running the **Setup Labels** workflow, or let your flows add them as needed.

That's it. The default free model needs only the auto-provided `GITHUB_TOKEN`.

## Versioning

Pin `<ref>` in the wrapper:

| Ref | Meaning |
|-----|---------|
| `@main` | Latest, moving. |
| `@v1` | Latest within a major tag (recommended). |
| `@<full-sha>` | Immutable pin for production. |

## Example flow (issue -> plan -> implement)

The repo ships this as its default `flows.yml`:

```yaml
defaults:
  model: opencode/deepseek-v4-flash-free
  agents_repository: tomzx/agents
  timeout_minutes: 30
flows:
  plan:
    rules:
      - id: generate-plan
        when: { event: issues, action: labeled, label: plan-needed }
        run: [ { skill: generate-plan } ]
      - id: on-plan-merged
        when: { event: pull_request, action: closed, merged: true, branch_prefix: plan/ }
        run: [ { labels: { add: [plan-approved], target: linked-issue } } ]
      - id: implement
        when: { event: issues, action: labeled, label: plan-approved }
        run: [ { skill: implement-plan } ]
```

See [`docs/flows.md`](docs/flows.md) for the full schema and recipes (triage, close-on-merge, per-step overrides).

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `OPENCODE_MODEL` | `opencode/deepseek-v4-flash-free` | opencode model id (provider/model) |
| `AGENTS_REPOSITORY` | `tomzx/agents` | repository providing skills |
| `flows.yml` `defaults` | - | per-flow overrides for model/agents-repo/timeout |

## Project structure

```
.github/
  workflows/
    dispatch.yml        reusable dispatcher (the engine)
    setup-labels.yml    syncs labels from flows.yml
    ci.yml              lints + tests the package
  wrappers/
    dispatch.yml        the one file consumers add to their repo
    setup-labels.yml
  flows.yml             the flow configuration (per repo)
  pr-description-template.md
src/llm_augmented_workflows/   the engine (installed as the `llmaw` CLI)
  engine.py             loader, matcher, step resolver (pure, unit-tested)
  route.py              event -> matched rules (matrix)
  run_steps.py          runs deterministic labels/shell steps
  sync_labels.py        creates/updates labels from flows.yml
  cli.py                `llmaw route | run-steps | sync-labels`
tests/test_engine.py    unit tests
examples/               example deterministic shell transitions
docs/flows.md           authoring guide + recipes
pyproject.toml          package + tooling (uv, hatchling, pytest, ruff)
```

Consumers never copy the engine. The dispatcher checks this repository out into `.llmaw/` on the worker and runs `uv run --project .llmaw llmaw ...`, pinning the version via the wrapper's `uses:` ref (and optional `framework-repository` / `framework-ref` inputs). Skills referenced by `run.skill` live in the external agents repository.

## Development

```bash
uv run --group dev ruff check src tests
uv run --group dev pytest -q
```

Runtime dependencies (pyyaml) are declared in `pyproject.toml`; the Python version is pinned in `.python-version`. Locally, `uv run llmaw route` runs the engine from the project environment.

## License

MIT - see [LICENSE](LICENSE).
