# Trackers and Local Mode

The engine core is tracker-agnostic. Flows are matched against a canonical event and every tracker read/mutation goes through a port, so the same `flows.yml` runs on GitHub Actions or entirely locally. This document covers the `tracker:` config, the local (trackerless) mode, and how to add a new tracker.

## Ports

Two protocols (defined in `src/llm_augmented_workflows/trackers/base.py`) are the seams:

| Port | Role | Adapters |
|---|---|---|
| `TrackerClient` | every tracker read/mutation: labels, comment, close, linked issue, label sync | `GithubCliClient` (`gh` CLI), `LocalYamlClient` (per-subject YAML files) |
| `EventSource` | produces the `CanonicalEvent` for one dispatch | `GithubActionsEventSource` (`GITHUB_EVENT_*`), `CliEventSource` (`llmaw trigger` flags) |

Labels are the only state the engine ever reads back (the label diff and continuous-mode chaining). Comments and closes are writes the engine does not read back. Title, body, branch, and merged arrive from the **event** (payload or trigger flags) and flow into the agent env (`ISSUE_TITLE`, `PR_BODY`, ...); clients never serve them.

The `when` vocabulary keeps GitHub event names as canonical terms, so no `flows.yml` changes when switching trackers.

## Configuration

One optional top-level key in `flows.yml`:

```yaml
tracker:
  kind: github        # github (default) | local
  # github: no further config (gh + GH_TOKEN as today)
  # local:
  state_dir: .llmaw/state
```

Selection precedence: `flows.yml tracker.kind` > env `LLMAW_TRACKER` > default `github`.

## GitHub mode (default)

Unchanged: mutations use `gh` with `GH_TOKEN`, events come from the GitHub Actions runtime, and comments carry the workflow-run footer. No dispatcher workflow changes are needed.

## Local mode (trackerless)

Run the whole label state machine from YAML files, no GitHub, no network. Agents run via your locally installed `opencode`; shell steps operate on your local git checkout (`git fetch origin` fails gracefully when no remote exists).

### State files

One YAML file per subject under `state_dir` (default `.llmaw/state`), named `<kind>-<id>.yml` (`issue-1.yml`, `pull-request-2.yml`), plus a shared `labels.yml` catalog:

```yaml
# .llmaw/state/issue-1.yml
labels: [llmaw:feature-request, llmaw:create-needs-assessment]
state: open            # open | closed
comments:              # append-only record of outcome feedback
  - { body: "...", at: 2026-08-17T12:00Z }
```

```yaml
# .llmaw/state/pull-request-2.yml (optional; only for linked-issue targets)
linked: issue-1        # explicit target for labels steps with target: linked-issue
```

Semantics:

- A missing subject file reads as `labels: []`, `state: open`; it is created on first mutation. No seeding step.
- `llmaw trigger issues labeled --issue 1 --label X` asserts `X` into state before rules run (a labeled event means the label is present, mirroring GitHub). GitHub state is authoritative there, so the assertion only applies to the local tracker.
- `llmaw sync-labels` writes the `labels.yml` catalog and applies `migrate_from` ([flows.md](flows.md#declared-labels-and-migration)) by rewriting the old name onto the new one in every subject file.
- Title, body, branch, and merged are event-time data, never persisted.
- Add `state_dir` to `.gitignore` if you do not want local runs committed.

### Driving it

```bash
# One-time setup: write the label catalog
llmaw sync-labels

# Emit an event (replaces the webhook trigger)
llmaw trigger issues labeled --issue 1 --label llmaw:feature-request
llmaw trigger issues opened  --issue 3 --title "Fix the flaky test"
llmaw trigger pull_request closed --pr 2 --merged --branch plan/issue-1   # synthetic merge

# Force-run a rule (replaces the Actions rule-id dry run)
llmaw run-rule --rule-id triage-new-issue --issue 1
```

`trigger` builds the canonical event, sets the same env contract the dispatcher sets (`ISSUE_NUMBER`, `ISSUE_TITLE`, `PR_TITLE`, `LABEL`, ...), routes, and executes the matched rules with the configured client.

Execution modes behave as documented in [`flows.md`](flows.md#execution-modes): `continuous` chains rules in-process by re-reading labels from the state file; `event-driven` runs one pass per `trigger`. Prefer `continuous` locally since there is no webhook loop to re-dispatch.

Rules gated on `merged: true, branch_prefix: plan/` fire via the synthetic merge trigger; the `on-*-merged` rule then relabels the linked issue (found via the `linked:` pointer or a `#N` in `--title`/`--body`). This simulates the full SDLC chain locally, including the human sign-off gates: the human runs the merge trigger.

`FLOWS_FILE` (default `.github/llmaw/flows.yml`) is read relative to the current directory; run from the repo root or export it.

## Adding a tracker

Implement the two protocols in a new module under `trackers/` and register it in `load_tracker`:

```python
class MyTrackerClient:
    name = "mytracker"
    def get_labels(self, ref): ...
    def add_labels(self, ref, labels): ...
    def remove_labels(self, ref, labels): ...
    def comment(self, ref, body): ...
    def close(self, ref, comment): ...
    def find_linked_subject(self, ref): ...
    def sync_labels(self, defs): ...

class MyWebhookEventSource:
    def event(self) -> CanonicalEvent | None: ...
```

Project native payloads into `CanonicalEvent` using the GitHub vocabulary (`event: issues`, `action: labeled`, `merged`, `branch`, ...). Nothing else in the engine moves.
