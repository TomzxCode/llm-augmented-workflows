# Authoring Flows

The dispatcher reads `.github/flows.yml` and routes GitHub events to rules. Each rule runs an ordered list of steps. This document is a practical reference with recipes.

## File shape

```yaml
defaults:        # applied to every agent step unless overridden
  model: opencode/deepseek-v4-flash-free
  agents_repository: tomzx/agents
  timeout_minutes: 30
  permissions: skip

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
| `labels` | add/remove labels (deterministic) | none |
| `shell` | run a shell script (deterministic) | none |
| `skill` | `opencode run --command <name>` from the agents repo | yes |
| `prompt` | run opencode with a local prompt file's contents | yes |

Deterministic steps run first (in listed order), then the agent step. One agent step per rule; chain more by emitting a label and matching it with another rule.

### `labels`

```yaml
- labels:
    add: [ready-to-plan]        # list or single string, optional
    remove: [feature-request]   # list or single string, optional
    target: subject             # subject (default) | linked-issue
```

`target: linked-issue` parses `#N` (or `closes|fixes|resolves|plan for issue #N`) from the PR title/body and labels that issue. Add/remove are diffed against current labels, so they are idempotent.

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
- Zero matches is a no-op; the `run-rule` job is skipped.
- A config error (bad step, unknown kind, rule without steps) fails the `route` job fast instead of misrouting.
- Dry-run any rule manually from the Actions tab via the dispatcher's `rule-id` input.
