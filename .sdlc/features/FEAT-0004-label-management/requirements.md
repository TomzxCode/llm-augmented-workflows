---
title: "Label Management"
status: approved
---

# Requirements: Label Management

## Overview

The `labels:` block of `flows.yml` is the declarative source of truth for repository labels.
A dedicated workflow (`setup-labels`) and CLI command (`llmaw sync-labels`) reconcile the repo with that declaration: creating missing labels, updating descriptions/colors on existing ones, and renaming predecessor labels onto their current names so issue history is preserved.
This keeps the label state-machine that drives routing in sync with configuration, without manual label housekeeping.

## Stakeholders

| Stakeholder | Interest |
|---|---|
| Flow author | Adding a label to config makes it appear on next run, no hardcoded lists |
| GitHub Actions operator | Safe, idempotent reconciliation that preserves issue history during renames |

## Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | Must | The system shall read the `labels:` block of `flows.yml` and, for each declared label, create it if missing or update its description/color if it already exists. |
| FR-02 | Must | Each declared label shall support a `migrate_from` field (a single name or a list) naming predecessor labels to rename onto the current name. |
| FR-03 | Must | A rename shall run `gh label edit <old> --name <new>` so GitHub moves every carrying issue onto the new name, preserving history. |
| FR-04 | Must | A rename shall be planned only when the new name does not yet exist; if both old and new already exist the pair shall be reported as a conflict (left untouched) for manual resolution. |
| FR-05 | Must | Migration planning shall be sequential within a pass: once a rename creates a target name, any further `migrate_from` entries pointing at that name become conflicts. |
| FR-06 | Must | `migrate_from` shall be idempotent: once renamed, the old name no longer exists and subsequent runs skip it. |
| FR-07 | Must | The system shall fetch the existing label set in a single `gh label list` call and plan all renames before mutating, so conflicts are surfaced up front. |
| FR-08 | Should | The system shall warn (not fail) when the `labels:` block is empty or absent. |

## Non-Functional Requirements

Order rows by priority: Must first, then Should, then May.

| ID | Priority | Category | Requirement |
|---|---|---|---|
| NFR-01 | Must | Reliability | Reconciliation shall be safe to re-run: create-then-update means an existing label is never recreated. |
| NFR-02 | Must | Compatibility | Renames must preserve issue history (GitHub moves carrying issues automatically). |
| NFR-03 | Should | Observability | Each action (create/update/rename/conflict) shall be logged. |

## Constraints

- `gh label edit <old> --name <new>` fails when the target name already exists, so two-existing-name conflicts cannot be auto-resolved.
- The reconcile runs on push to `main` and on `workflow_dispatch`, using the auto-provided `GITHUB_TOKEN` (issues: write).

## Acceptance Criteria

Every FR and NFR shall have at least one acceptance criterion.

- [ ] **FR-01**
    - **Given** a declared label not present in the repo
    - **When** `llmaw sync-labels` runs
    - **Then** the label is created with the declared description and color
- [ ] **FR-03**
    - **Given** a declared label with `migrate_from: [old-name]` and `old-name` exists but the new name does not
    - **When** sync runs
    - **Then** `old-name` is renamed onto the new name and carrying issues follow
- [ ] **FR-04**
    - **Given** both `old-name` and the new name already exist
    - **When** sync runs
    - **Then** a conflict is logged and both labels are left untouched
- [ ] **FR-06**
    - **Given** a previously-migrated label
    - **When** sync runs again
    - **Then** the migration is skipped (old name gone)
- [ ] **NFR-01**
    - **Given** an already-existing declared label
    - **When** sync runs
    - **Then** the create attempt fails softly and the label is updated in place instead

## Conflicts

None identified yet.

## Open Questions

1. Should the reconcile delete labels that are no longer declared? (Currently it only creates/updates/renames; undeclared labels are left alone.)
