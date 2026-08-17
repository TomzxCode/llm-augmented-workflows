# LLM Augmented Workflows

A config-driven automation engine for issue trackers, powered by opencode. Describe your flows in one `flows.yml` file; the dispatcher routes events to the right agent skills (and token-free label/shell steps). Run it on GitHub Actions, or entirely locally with the label state in YAML files. No per-flow workflow files, no copied boilerplate.

## How it works

```
GitHub event (issue labeled, PR merged, comment, ...)
   |
   v
dispatch.yml  reads flows.yml  ->  route matches rule(s)
   |
   v
for each matched rule, run-rule runs its whole `run` in one pass:
   labels/shell (pre) -> skill (opencode) -> labels/shell (post) -> on_outcome
   |
   v
the agent acts on GitHub (relabel, comment, open PR, close) -> emits new events
```

State lives in the tracker (GitHub labels, or per-subject YAML files in local mode). The engine is stateless. Terminal outcomes emerge naturally: an agent closes an issue (won't fix), or a PR merges and an `on-merge` rule closes the linked issue.

### Execution modes

Each matched rule's pipeline runs in one job. Two modes control what happens after that pipeline:

- **event-driven** (default): the rule runs once and the job ends; the relabel emits a new event that re-triggers the dispatcher for the next phase (one job per phase).
- **continuous**: the same job keeps advancing to the next rule based on the labels each rule adds, until `llmaw:needs-human` appears or the chain reaches a resting state (one job per pipeline).

Set it under `defaults.execution` / `flows.<name>.execution`, force it per-dispatch via the `execution` input or the `LLMAW_EXECUTION` repo variable. See [`docs/flows.md`](docs/flows.md#execution-modes) for details.

## Features

- **One config file** (`.github/llmaw/flows.yml`) defines every flow as event-matched rules.
- **Tracker-independent core**: GitHub via `gh` by default, or a local trackerless mode with per-subject YAML state files (see [`docs/trackers.md`](docs/trackers.md)).
- **Ordered pipeline** per rule: `labels`/`shell` (token-free, before or after the agent), `skill`/`prompt` (opencode agents), and `on_outcome` (routes the agent's verdict to labels/close/comment).
- **Two execution modes**: `event-driven` (one job per phase) or `continuous` (one job per pipeline, chaining rules until `needs-human`).
- **Token-free transitions** like relabeling (the `labels` step) cost zero tokens.
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

2. Add `.github/llmaw/flows.yml` describing your flows (see [`docs/flows.md`](docs/flows.md) and the example in this repo).

3. (Optional) Set repo/org variables to override the defaults:
   - `OPENCODE_MODEL` - opencode model id (default `opencode/deepseek-v4-flash-free`)
   - `AGENTS_REPOSITORY` - skills repo as `owner/repo` (default `tomzx/agents`)
   - `LLMAW_EXECUTION` - `continuous` or `event-driven` (default resolves from `flows.yml`, ultimately `event-driven`)
   - `LLMAW_MAX_ITERATIONS` - iteration cap for continuous mode (default `30`)

4. Create the labels declared under `labels:` by running the **Setup Labels** workflow, or let your flows add them as needed. Entries may also declare `migrate_from` to rename predecessor labels onto the new name (carrying issues follow); see [`docs/flows.md`](docs/flows.md#declared-labels-and-migration).

That's it. The default free model needs only the auto-provided `GITHUB_TOKEN`.

## Run locally (no GitHub)

The same flows can run trackerless, with the label state machine in YAML files under `.llmaw/state/`:

```yaml
# in flows.yml
tracker:
  kind: local
  state_dir: .llmaw/state
```

```bash
llmaw sync-labels                                             # write the label catalog
llmaw trigger issues labeled --issue 1 --label llmaw:feature-request
llmaw trigger pull_request closed --pr 2 --merged --branch plan/issue-1   # synthetic merge
```

Agents run via your local `opencode`; continuous mode chains the whole pipeline in one command. See [`docs/trackers.md`](docs/trackers.md).

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
| `LLMAW_EXECUTION` | `event-driven` | force `continuous` or `event-driven` (else resolved from `flows.yml`) |
| `LLMAW_MAX_ITERATIONS` | `30` | iteration cap for continuous mode |
| `LLMAW_TRACKER` | `github` | tracker kind when `flows.yml` has no `tracker.kind` |
| `flows.yml` `tracker` | - | `kind: github \| local` (+ `state_dir` for local) |
| `flows.yml` `defaults` | - | per-flow overrides for model/agents-repo/timeout/execution |

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
  llmaw/
    flows.yml           the flow configuration (per repo)
    scripts/            ensure-branch.sh, commit-sdlc.sh (resolved from main)
  pr-description-template.md
src/llm_augmented_workflows/   the engine (installed as the `llmaw` CLI)
  engine.py             loader, matcher, step resolver (pure, unit-tested)
  route.py              event -> matched rules
  run_steps.py          applies labels/shell steps (shared helper)
  apply_outcome.py      maps an agent's verdict to labels/close/comment
  run_rule.py           drives a rule's whole run: pre -> agent -> post -> on_outcome
  sync_labels.py        creates/updates/migrates labels from flows.yml
  cli.py                `llmaw route | run-rule | run-steps | apply-outcome | sync-labels | trigger`
  trackers/
    base.py             TrackerClient/EventSource ports, SubjectRef, CanonicalEvent
    github.py           gh CLI client + GitHub Actions event source
    local.py            per-subject YAML state client + CLI event source
tests/                  unit + local end-to-end tests
examples/               example deterministic shell transitions
docs/flows.md           authoring guide + recipes
docs/trackers.md        tracker config + local mode
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
