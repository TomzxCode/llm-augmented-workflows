---
title: "Label Management"
status: approved
---

# Specification: Label Management

## Overview

Label management lives in `sync_labels.py` (`llmaw sync-labels`), driven by the `.github/workflows/setup-labels.yml` workflow.
It loads the `labels:` block, fetches the existing label set once, plans all renames (resolving conflicts up front), performs the renames, then create-or-updates each declared label.
All mutations use the `gh` CLI with `GITHUB_TOKEN`.

## Architecture

```
setup-labels.yml (on push to main / workflow_dispatch)
  -> checkout repo + engine into .llmaw/
  -> uv run --project .llmaw llmaw sync-labels
        load_flows -> labels block
        existing = list_existing_labels()            (single gh label list)
        renames, conflicts = plan_migrations(labels, existing)
        for (old,new) in renames: rename_label(old,new)   (gh label edit old --name new)
        for (old,new) in conflicts: log warning
        for label in labels: sync_label(name, description, color)
              gh label create ...  -> on failure: gh label edit ...
```

## Data Models

### Declared label (`flows.yml` `labels:` entry)

| Field | Type | Constraints | Description |
|---|---|---|---|
| name | str | required | Current label name |
| description | str | optional | Label description |
| color | str | optional | Six-digit hex color (no `#`) |
| migrate_from | str \| list[str] | optional | Predecessor name(s) to rename onto `name` |

## API Contracts

No HTTP API. The contract is the `llmaw sync-labels` command and its workflow.

### `llmaw sync-labels`

**Inputs (environment)**

| Field | Type | Required | Description |
|---|---|---|---|
| FLOWS_FILE | path | no (default `.github/llmaw/flows.yml`) | Config file to read labels from |
| GITHUB_TOKEN | str | yes | Token for `gh label` mutations |

**Behavior**: reconcile the repo's labels with the declared block (create/update/rename, report conflicts).

## Sequences

### Migration planning (sequential within a pass)

```
seen = set(existing)
for label in declared:
  new = label.name
  for old in label.migrate_from:
    if old not in seen: skip                      (already migrated / never existed)
    if new in seen: conflicts.add((old, new))     (cannot rename onto existing)
    else: renames.add((old, new)); seen.discard(old); seen.add(new)
  seen.add(new)
```

## Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Plan then mutate | Fetch all labels, plan renames, then act | Surfaces all conflicts before any mutation |
| Rename via `gh label edit --name` | Use GitHub's rename | Carrying issues follow automatically, preserving history |
| Create-then-update | Try create, fall back to edit | Idempotent: existing labels update in place rather than erroring |
| No deletion | Undeclared labels are left alone | Avoids accidentally removing human/external labels |

## Risks and Unknowns

1. A two-existing-name conflict requires manual re-tagging plus delete; the engine only reports it.
2. The single `gh label list` call is capped at 1000 labels; larger repos would need pagination.
3. Color/description updates on heavily-used labels are cheap but visible in the audit log.

## Out of Scope

- The `labels` deterministic step inside a rule pipeline (handled by FEAT-0002).
- Routing decisions based on labels (handled by FEAT-0001).
