# Authoring Flows

The dispatcher reads `.github/llmaw/flows.yml` (in the consumer repo) and routes GitHub events to rules. Each rule runs an ordered list of steps. This document is a practical reference with recipes.

## File shape

```yaml
defaults:        # applied to every agent step unless overridden
  model: opencode/deepseek-v4-flash-free
  agents_repository: tomzx/agents
  timeout_minutes: 30
  execution: event-driven   # or "continuous"

labels:          # created/updated by the setup-labels workflow
  - name: feature-request
    description: Triaged feature request
    color: 0E8A16

flows:           # grouping is organizational; routing is flat across all flows
  feature-request:
    description: ...
    rules:
      - id: triage              # unique
        when: { ... }           # event matcher
        run: [ ... ]            # ordered steps
```

## `when` matchers

All specified fields are ANDed. Omit a field to wildcard it.

| Field | Applies to | Meaning |
|-------|------------|---------|
| `event` | all | `issues`, `pull_request`, `issue_comment`, `pull_request_review_comment` |
| `action` | all | `opened`, `labeled`, `closed`, `created`, ... |
| `label` | issues, pull_request | label name on a `labeled` event |
| `merged` | pull_request | require `merged` true/false on `closed` |
| `branch_prefix` | pull_request | match PR head branch by prefix |
| `body_contains` | issues, pull_request | substring in the body |

## Steps

`run` is an ordered list. Each item has exactly one key.

| Step | Effect | Tokens |
|------|--------|--------|
| `labels` | add/remove labels | none |
| `shell` | run a shell script | none |
| `skill` | `opencode run --command <name>` from the agents repo | yes |
| `prompt` | run opencode with a local prompt file's contents | yes |
| `on_outcome` | after the agent, switch on its emitted verdict to apply labels/close/comment | none |

`run` is an ordered pipeline. `labels`/`shell` may appear on either side of the agent (pre or post); the only hard rule is that `on_outcome` must follow the agent (it reads `$OUTCOME_YAML` the agent writes) and come last. Execution order is: pre `labels`/`shell` → agent → post `labels`/`shell` → `on_outcome`. Post-steps run only if the agent succeeded, so they're the right place to consume a label after the skill that matched it. One agent step per rule; chain more by emitting a label and matching it with another rule.

### `labels`

```yaml
- labels:
    add: [ready-to-plan]        # list or single string, optional
    remove: [feature-request]   # list or single string, optional
    target: subject             # subject (default) | linked-issue
```

`target: linked-issue` parses `#N` (or `closes|fixes|resolves|plan for issue #N`) from the PR title/body and labels that issue. Add/remove are diffed against current labels, so they are idempotent.

### `shell`

```yaml
- shell: examples/close-linked-issue.sh                                   # plain string
- shell: [.github/llmaw/scripts/commit-sdlc.sh, "draft requirements"]     # argv: script + args
```

The value is either a plain string (the script path) or a list whose first element is the script and the rest are positional arguments (`$1`, `$2`, ... inside the script). Use the list form to parameterize a shared script per phase, e.g. a phase-specific commit subject. Ambient context (`ISSUE_NUMBER`, `PR_TITLE`, ...) still arrives via the environment set by the dispatcher.

### `skill` / `prompt`

```yaml
- skill: triage-feature          # command from agents_repository
- prompt: .agents/commands/x.md  # local file
# per-step overrides:
- skill:
    name: triage-feature
    model: opencode/gpt-4o
    agents_repository: myorg/agents
    timeout_minutes: 45
```

Model and agents-repository resolve as: step override > `defaults` > workflow input > repo variable (`OPENCODE_MODEL`, `AGENTS_REPOSITORY`) > hardcoded default.

### `on_outcome`

A post-agent step. The skill, as its final action, writes a YAML file to the path in `$OUTCOME_YAML` (set by the dispatcher):

```yaml
# $OUTCOME_YAML
verdict: approved        # the value the cases below switch on
reason: ...              # required, overrides the action's hardcoded comment
```

`on_outcome` maps each `verdict` value to an action. The optional `_` key is the fallback when no case matches. An action may carry a `labels` operation (same `{add, remove, target: subject | linked-issue}` shape as a `labels` step), `close` the subject, and/or post a `comment`.

An action opts in to the skill's feedback with `post_reason: true`. When set, the outcome's `reason` is posted instead of the action's hardcoded `comment` (which becomes a fallback for when the skill wrote none). Without `post_reason`, the action posts only its hardcoded `comment` and the `reason` is not surfaced.

```yaml
run:
  - skill: create-needs-assessment
  - on_outcome:
      approved:   { labels: { add: [llmaw:needs-approved] } }
      rejected:   { close: true, comment: "Closing as wontfix.", post_reason: true }
      needs-info: { comment: "Need more info.", post_reason: true }
      _:          { comment: "No verdict produced; needs review." }
```

In this example the `approved` action stays silent, `rejected`/`needs-info` post the skill's context-specific `reason` (falling back to the hardcoded text), and the `_` fallback uses its hardcoded comment (the skill produced no usable reason).

```yaml
run:
  - skill: create-needs-assessment
  - on_outcome:
      approved:   { labels: { add: [llmaw:needs-approved] } }
      rejected:   { close: true, comment: "Closing as wontfix." }
      needs-info: { labels: { add: [llmaw:needs-info] } }
      _:          { comment: "No verdict produced; needs review." }
```

Rules:

- `on_outcome` must follow the agent step and reads `$OUTCOME_YAML` from the same run.
- Both `verdict` and `reason` are required. A missing `reason` triggers the continuation (the model is asked once to write a complete outcome).
- A missing/invalid outcome file yields `verdict: unknown`; only the `_` case (if any) applies.
- If the skill writes no outcome, the engine resumes its opencode session once (`opencode run --continue`) and asks the model to write `$OUTCOME_YAML` before applying the fallback above. This only fires when `$OUTCOME_YAML` is set and the rule has an `on_outcome`.
- At least one verdict case (besides `_`) is required.
- Skills stay label-agnostic: they emit a domain verdict; the verdict-to-label mapping lives here.

## Execution modes

The dispatcher runs each matched rule's pipeline (pre → agent → post → `on_outcome`) in one job. What happens **after** that pipeline is governed by the execution mode:

| Mode | Behavior |
|------|----------|
| `event-driven` (default) | The rule runs once, then the job ends. The `on_outcome` relabel emits a new `issues:labeled` event, which re-triggers the dispatcher for the next phase. Each phase is its own GitHub Actions job. |
| `continuous` | After the seed rule(s) finish, the same job re-reads the issue's labels, finds the rule whose `when.label` matches a **newly added** label, runs it, and repeats until a terminal condition is hit. The whole pipeline runs in a single job. |

### Choosing the mode

Resolution order (first wins):

1. Workflow `execution` input, or the `LLMAW_EXECUTION` repo/org variable (`continuous` or `event-driven`).
2. `flows.<name>.execution` for the matched rule's flow.
3. `defaults.execution`.
4. `event-driven`.

```yaml
defaults:
  execution: continuous      # default for every flow
flows:
  feature:
    execution: continuous    # or set it per flow
    rules: [...]
  review:
    execution: event-driven  # opt a flow back out
    rules: [...]
```

Force a mode for one dispatch from the Actions tab (the dispatcher's `execution` input) or a repo variable:

```yaml
# repo variable
LLMAW_EXECUTION = continuous
```

### How continuous mode picks the next rule

After each rule's `on_outcome` runs, the engine fetches the issue's current labels and computes the set that was **added** since the previous iteration. It then looks for a rule with `when: { event: issues, action: labeled, label: <one of the new labels> }` and runs it. PR/comment/merge rules and event-agnostic rules are never auto-chained (the chain keys on the issue label state-machine only).

This means:

- A rule that opens a PR (e.g. `create-plan`, whose `on_outcome: approved: {}` adds no label) **naturally ends the loop** — the chain resumes in a later dispatch when the PR merges and relabels the linked issue.
- Each phase must add the label its successor matches, exactly as it already does for event-driven chaining. No config change is needed to the rules themselves.

### Stopping the loop

The continuous loop stops when:

- `llmaw:needs-human` is present on the issue, or
- a rule adds no new label, or
- the newly-added label(s) match no rule, or
- the iteration cap is reached (default 30, overridable via the `LLMAW_MAX_ITERATIONS` repo variable).

Continuous mode only loops for **issue** subjects. PR/comment subjects run their seed rule once without looping; any relabel they cause on a linked issue triggers its own dispatch (which will itself be continuous).

## Recipes

### Feature request triage with go/no-go

```yaml
flows:
  feature-request:
    rules:
      - id: triage-feature
        when: { event: issues, action: labeled, label: feature-request }
        run:
          - labels: { remove: [feature-request], add: [triaged] }
          - skill: triage-feature-request   # decides: needs-info / ready-to-plan / wontfix(+close)
```

### Close the linked issue when an implementation PR merges

```yaml
      - id: close-on-impl-merged
        when: { event: pull_request, action: closed, merged: true, branch_prefix: impl/ }
        run:
          - shell: examples/close-linked-issue.sh
```

### Relabel on plan merge (no agent)

```yaml
      - id: on-plan-merged
        when: { event: pull_request, action: closed, merged: true, branch_prefix: plan/ }
        run:
          - labels: { add: [plan-approved], target: linked-issue }
```

## Notes

- The engine is stateless. State lives in GitHub (labels, PRs, issues).
- Tooling is pinned to main. The dispatcher snapshots `.github/llmaw/` (this file + the scripts) from `main` into `$LLMAW_TOOLING_ROOT` before any rule runs, and scripts/`flows.yml` resolve from there. So even though `ensure-branch.sh` switches the working tree to the per-issue branch (so skills edit and commit branch content), the automation that drives the flow always runs from `main` and fixes apply to in-flight issues the moment they land.
- Each matched rule runs in one pass: pre `labels`/`shell` → agent → post `labels`/`shell` → `on_outcome`.
- In `continuous` mode that pass repeats in the same job, advancing on each newly-added label until `needs-human` or a resting state (see [Execution modes](#execution-modes)).
- Zero matches is a no-op; the `Run matched rules` step is skipped.
- A config error (bad step, unknown kind, rule without steps) fails fast at the route step instead of misrouting.
- Dry-run any rule manually from the Actions tab via the dispatcher's `rule-id` input.
