# Design Plan: Tracker-Independent Workflows

## Goal

Decouple the engine from GitHub so the same `flows.yml` drives workflows in two settings:

1. **GitHub Actions** (today's behavior, byte-for-byte unchanged).
2. **Local, trackerless**: the label state machine lives in per-subject YAML state files, events are emitted from the CLI, agents run via a locally installed `opencode`. No network, no GitHub.

The I/O is carved behind ports (`TrackerClient`, `EventSource`), so other trackers (GitLab, Linear) remain possible later as additive adapters with no engine changes; building them is explicitly out of scope here.

Compatibility rules:

- Existing `flows.yml` files keep working unchanged.
- The `when` vocabulary keeps GitHub event names (`issues`, `pull_request`, `labeled`, ...) as the **canonical** terms; other trackers translate into them. No config migration.
- The GitHub path keeps using `gh` + `GH_TOKEN` exactly as today.

## Current Coupling Inventory

Where GitHub is hardwired today:

| Concern | Location | Coupling |
|---|---|---|
| Event ingestion | `route.py` (`GITHUB_EVENT_PATH` / `GITHUB_EVENT_NAME`) | Actions env contract |
| Event matching | `engine.matches()` | GitHub payload structure (`label.name`, `pull_request.merged`, `head.ref`) |
| Label read | `run_steps._current_labels()` | `gh issue view --json labels` |
| Label write | `run_steps.apply_labels()` | `gh issue edit --add-label/--remove-label` |
| Comment / close | `apply_outcome._post_comment()` / `_close()` | `gh issue comment/close` |
| Linked issue | `run_steps._find_linked_issue()` | `closes #N` regex over PR title/body env |
| Subject identity | `run_steps._current_subject()` | `ISSUE_NUMBER` / `PR_NUMBER` env |
| Label sync | `sync_labels.sync_label()` | `gh label create/edit` |
| Continuous fetch | `run_rule._fetch_labels()` | reuses the `gh` label read |
| Comment footer | `apply_outcome._with_run_link()` | Actions run URL env |
| Orchestration | `.github/workflows/dispatch.yml` | Actions triggers, matrix, app token |

`engine.py` (load / normalize / split / `find_next_rules` / label diff) is already pure and tracker-free; only `matches()` assumes the GitHub payload structure. The refactor is about carving the I/O out of `run_steps.py`, `apply_outcome.py`, `route.py`, and `sync_labels.py` behind ports.

## Abstractions: Three Ports

### Port 1: `TrackerClient` (state read/write)

One protocol owns every tracker mutation and query. Today these calls are inlined in `run_steps.py` / `apply_outcome.py` / `sync_labels.py`.

```python
@dataclass(frozen=True)
class SubjectRef:
    kind: str   # "issue" | "pull_request" (canonical terms)
    id: str     # "42"

class TrackerClient(Protocol):
    name: str

    def get_labels(self, ref: SubjectRef) -> list[str]: ...
    def add_labels(self, ref: SubjectRef, labels: list[str]) -> None: ...
    def remove_labels(self, ref: SubjectRef, labels: list[str]) -> None: ...
    def comment(self, ref: SubjectRef, body: str) -> None: ...
    def close(self, ref: SubjectRef, comment: str | None) -> None: ...
    def find_linked_subject(self, ref: SubjectRef) -> SubjectRef | None: ...
    def sync_labels(self, defs: list[dict]) -> None: ...
```

Labels are the only state the engine ever reads back (label diff, continuous chaining). The agent env contract (`ISSUE_TITLE`, `PR_BODY`, `PR_BRANCH`, ...) is derived from the **event** by the event source, exactly as the Actions dispatcher derives it from the payload today; clients never serve it. `comment`/`close` are writes the engine does not read back.

Adapters (built here):

| Adapter | Implementation notes |
|---|---|
| `GithubCliClient` | Wraps `gh`. Literally the code currently inlined in `run_steps.py` / `apply_outcome.py`, extracted. Owns the run-link comment footer. Default everywhere; zero behavior change. |
| `LocalYamlClient` | Reads/writes the per-subject YAML state files (see [Local mode](#local-mode-trackerless)). |

The protocol is the extension seam: a GitLab (`glab`) or Linear client later is a new module implementing `TrackerClient`, nothing else moves.

Injection: `run_steps.apply_labels(step, client)`, `run_rule._fetch_labels(..., client)`, `apply_outcome.apply(on_outcome, client, ...)`, `sync_labels(client)`. The CLI constructs the client once at startup and threads it through. No module-level singleton; tests pass fakes explicitly (same pattern as the existing `_gh` monkeypatching, one level up).

### Port 2: `EventSource` (ingestion)

`route.py` currently reads `GITHUB_EVENT_*`. Replace with one protocol returning a canonical event:

```python
class EventSource(Protocol):
    def event(self) -> CanonicalEvent | None: ...
```

```python
@dataclass(frozen=True)
class CanonicalEvent:
    event: str            # canonical name, GitHub vocabulary: issues | pull_request | issue_comment | ...
    action: str | None    # opened | labeled | closed | created | ...
    subject: SubjectRef
    label: str | None
    merged: bool | None
    branch: str | None
    body: str | None
    comment: dict | None  # {author, body, type: general|inline}
    raw: dict             # original payload for exotic needs
```

`engine.matches()` changes signature from `(when, event_name, payload_dict)` to `(when, CanonicalEvent)`. Mechanical change, identical field semantics, same `when` schema. `find_next_rules`, `rule_to_matrix`, and all normalization stay untouched.

Adapters (built here):

| Adapter | Implementation notes |
|---|---|
| `GithubActionsEventSource` | Reads `GITHUB_EVENT_PATH` / `GITHUB_EVENT_NAME`, projects the payload into `CanonicalEvent`. Default. |
| `CliEventSource` | Builds `CanonicalEvent` from `llmaw trigger` CLI flags (`--title`/`--body`/`--branch`/`--merged`); derives the agent env from them, mirroring the dispatcher. The state files hold only label state. Powers local mode. |

As with the client, other trackers' webhook event sources slot in later behind the same protocol.

### Port 3: `Runner` (pipeline execution)

How a matched rule's pipeline (pre `labels`/`shell` -> agent -> post -> `on_outcome`) is executed:

- **ActionsRunner** (implicit): today's `dispatch.yml` matrix job that invokes `uv run llmaw run-rule` per rule. Stays as-is.
- **LocalRunner**: `run_rule.main()` **is** the runner already; it is a single Python process driving the whole pipeline. Local mode = same code + `LocalYamlClient` + local `opencode` on PATH. No new abstraction to build, just documentation of this role.

## Config Model

One new optional top-level key in `flows.yml`; everything else unchanged:

```yaml
tracker:
  kind: github        # github (default) | local
  # github: no further config (gh + GH_TOKEN as today)
  # local:
  state_dir: .llmaw/state
```

Selection precedence: `flows.yml tracker.kind` > env `LLMAW_TRACKER` > default `github`.

A factory `load_tracker(flows_raw, env) -> TrackerClient` in `trackers/__init__.py` constructs the adapter once per CLI invocation.

## Local Mode (Trackerless)

The headline use case: run the whole label state machine from a YAML file, no GitHub.

### State files (one per subject)

Owned entirely by `LocalYamlClient`. The engine reads exactly one thing from tracker state: labels. A subject file is therefore mostly labels, plus write-only record for later inspection. Files are named `<kind>-<id>.yml` with the kind's underscore as a hyphen (`issue-1.yml`, `pull-request-2.yml`):

```
.llmaw/state/
  issue-1.yml
  issue-3.yml
  pull-request-2.yml     # only needed to carry a `linked:` pointer (see below)
  labels.yml             # the label catalog, written by llmaw sync-labels
```

```yaml
# .llmaw/state/issue-1.yml
labels: [llmaw:feature-request, llmaw:create-needs-assessment]
state: open            # open | closed; terminal marker, written by `close`, never read for routing
comments:              # append-only record of outcome feedback, for human inspection
  - { body: "...", at: 2026-08-17T12:00Z }
```

Everything else is event-time data, not state. Title, body, branch, merged, and the trigger label arrive via `llmaw trigger` flags, flow into the `CanonicalEvent` and the agent env (`ISSUE_TITLE`, `PR_BODY`, ...), and are not persisted. This mirrors GitHub, where the dispatcher reads them from the event payload, never from a later API call.

Consequences:

- `trigger issues labeled --issue 1 --label X` **asserts the label into state** (X is added to `labels`) before rules run, mirroring GitHub semantics where a labeled event means the label is present.
- A missing subject file reads as `labels: []`, `state: open`; it is created on first mutation. No seeding step needed.
- `find_linked_subject` resolution: a pseudo-MR file may carry an explicit pointer (below); otherwise the same `#N` regex runs over the event's `PR_TITLE`/`PR_BODY` env.

```yaml
# .llmaw/state/pull-request-2.yml (optional)
linked: issue-1        # explicit target for labels steps with target: linked-issue
```

Why one file per subject rather than one big state file:

- Each file is small and self-contained, natural to inspect or hand-edit while iterating on a flow.
- Subjects are independent: every read/mutate touches only that subject's file, and writes are atomic per file (temp + rename). Two concurrent local runs on different subjects never clobber each other.
- The directory listing is the subject registry; there is no central index to keep consistent.

Method mapping:

| `TrackerClient` method | State-file operation |
|---|---|
| `get_labels` | read `labels` in the subject's file (missing file -> `[]`) |
| `add_labels` / `remove_labels` | mutate that list, atomic rewrite of the subject's file |
| `comment` | append to `comments` in the subject's file |
| `close` | set `state: closed` in the subject's file |
| `find_linked_subject` | `linked:` pointer in the pseudo-MR file, else `#N` over event title/body; returns `None` if the target file does not exist |
| `sync_labels` | write `labels.yml` |

### CLI entry points

```bash
# One-time setup: write the label catalog:
llmaw sync-labels                          # writes .llmaw/state/labels.yml

# Emit an event (replaces the webhook trigger); `labeled` asserts its label into state:
llmaw trigger issues labeled --issue 1 --label llmaw:feature-request
llmaw trigger issues opened  --issue 3 --title "Fix the flaky test"
llmaw trigger pull_request closed --pr 2 --merged --branch plan/issue-1   # synthetic merge

# Force-run a rule (replaces the Actions rule-id dry-run):
llmaw run-rule --rule-id triage-new-issue --issue 1
```

`llmaw trigger` = build `CanonicalEvent` -> `route` -> execute matched rules with `LocalYamlClient`. In `continuous` execution the chain advances in-process by re-reading labels from the subject's state file (the existing `_run_continuous` loop, client-threaded). In `event-driven` execution each `trigger` is one pass, mirroring one Actions dispatch. Recommendation for local use: `execution: continuous`, since there is no webhook loop to re-dispatch.

Agent steps run via the local `opencode` on PATH (skills resolved from the locally configured agents directory, no clone needed). Shell steps work unchanged: `ensure-branch.sh` and `commit-sdlc.sh` operate on the local git checkout, and `git fetch origin` already fails gracefully when no remote exists.

### Merge rules locally

Rules gated on `merged: true, branch_prefix: plan/` need a merge event. Locally, `llmaw trigger pull_request closed --pr 2 --merged --branch plan/issue-1` constructs it synthetically; the `on-plan-merged` rule then relabels the linked issue's state file. This gives a fully local end-to-end simulation of the whole SDLC chain, including the human sign-off gates (the human runs the merge trigger; there is no merge to perform).

## What Stays the Same

- The `when` / `run` / `on_outcome` schema, execution modes, `find_next_rules` chaining, label-diff idempotency.
- `opencode run` agent invocation (already tracker-agnostic).
- Shell-step scripts (git-based; they work on GitHub and locally).
- Skills stay label-agnostic: they emit verdicts; the verdict-to-label mapping lives in `flows.yml`.
- The GitHub Actions workflows (`dispatch.yml`, wrappers, CI). `GithubCliClient` is the default adapter; nothing changes on the Actions path.

## Proposed File Layout

```
src/llm_augmented_workflows/
  engine.py            # matches() takes CanonicalEvent; rest unchanged
  route.py             # uses EventSource instead of GITHUB_EVENT_* directly
  run_rule.py          # threads TrackerClient; subject/rule also from CLI flags
  run_steps.py         # apply_labels(step, client); gh code moves to GithubCliClient
  apply_outcome.py     # apply(..., client); gh code moves to GithubCliClient
  sync_labels.py       # uses client.sync_labels()
  cli.py               # adds `trigger`; client + event-source factory
  trackers/
    __init__.py        # load_tracker() factory
    base.py            # TrackerClient, EventSource protocols; SubjectRef; CanonicalEvent
    github.py          # GithubCliClient, GithubActionsEventSource
    local.py           # LocalYamlClient, CliEventSource
```

## Migration Path (incremental, no behavior change)

1. **Extract the port + GitHub adapter.** Create `trackers/base.py` and `trackers/github.py`; move the `gh` calls out of `run_steps.py` / `apply_outcome.py` / `sync_labels.py`; thread the client through. All existing tests stay green (they mock `_gh` one level below; port them to fake clients). Zero behavior change.
2. **Generalize `matches()`** to take `CanonicalEvent`; `GithubActionsEventSource` projects `GITHUB_EVENT_PATH` payloads into it. Engine tests updated mechanically.
3. **Add `tracker:` config** and the `load_tracker()` factory; GitHub remains the default.
4. **Add local mode**: `LocalYamlClient`, `CliEventSource`, `llmaw trigger`, `run-rule --issue/--pr/--rule-id`. New tests for the local adapter.
5. **Docs**: new `docs/trackers.md`; README quickstart gains a local-mode section.

Steps 1-3 are pure refactor guarded by the existing suite. Step 4 delivers the trackerless goal.

## Testing Strategy

- **Refactor safety (steps 1-3)**: existing `test_engine.py`, `test_run_rule.py`, `test_run_steps.py`, `test_apply_outcome.py` keep passing, with mocks lifted from `_gh` to the client protocol.
- **`trackers/github.py`**: unit tests with monkeypatched `subprocess.run` (port the current `_capture_gh` pattern).
- **`trackers/local.py`**: unit tests over a `tmp_path` state dir covering every method (including seeding on first reference); green-path test seeding a subject file and asserting label transitions, comment log, close, and `find_linked_subject`.
- **Green-path end-to-end (local)**: seed a state dir, run a two-rule chain with the agent monkeypatched, assert the subject files relabel and `comments` grow. Continuous mode covered by the existing `_run_continuous` tests, re-run against the local client.
- `uv run --group dev ruff check src tests` and `uv run --group dev pytest -q` before every commit.

## Explicitly Out of Scope

- GitLab and Linear adapters. The ports exist precisely so these can be added later as standalone modules; nothing here builds them.
- A resident daemon or `llmaw watch` (file/dir tailing event source). `trigger` + `run-rule` cover the ask; watch can be added later behind the same `EventSource` port.
- Hosted webhook ingestion (a service that receives webhooks and dispatches). Local CI wiring can come later as another Runner.
- Renaming the canonical event vocabulary to neutral terms.
- Cross-tracker flows (one rule run against two trackers).
- Changes to the GitHub Actions dispatch workflow beyond what the refactor requires (none expected).
