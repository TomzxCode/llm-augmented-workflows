---
issue: "#17"
title: "Implement directly from issue"
status: approved
---

# Requirements: Implement directly from issue

## Overview

The full 14+ phase SDLC pipeline (triage, needs, requirements, existing-solutions, codebase-analysis, feasibility, specifications, telemetry, observability, plan, tasks, tests, implementation) imposes unnecessary overhead on simple, well-understood features where the scope is already clear from the issue description. This feature adds an express path that routes eligible issues directly from triage to implementation, consuming fewer tokens and delivering code faster, while still producing a minimal artifact trail for traceability. Complex features continue through the full pipeline.

## Stakeholders

| Stakeholder | Interest |
|---|---|
| Project owner (tomzx) | Wants to replace vibe-kanban with a pure GitHub workflow; needs fast delivery of simple features |
| Contributors | Want to contribute simple changes without navigating a heavy planning pipeline |
| LLM agent automation | Should conserve tokens by skipping low-value planning phases for simple features |
| Code reviewer | Needs enough context (artifacts, PR description) to review the implementation |

## Functional Requirements

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | Must | The system shall classify a feature as eligible or ineligible for the express path based on configurable criteria |
| FR-02 | Must | The system shall produce an implementation from an eligible issue without running the planning phases (requirements, existing-solutions, codebase-analysis, feasibility, specifications, telemetry, observability, plan, tasks) |
| FR-03 | Must | The system shall produce a minimal artifact trail for every express-path feature (at minimum: an artifact recording that the express path was used and why) |
| FR-04 | Must | The system shall fall back to the full SDLC pipeline when a feature is classified as ineligible for the express path |
| FR-05 | Should | The system shall log the classification decision and rationale to the issue or a corresponding artifact |
| FR-06 | Should | The system shall allow a human to override the classification by adding or removing a label on the issue |
| FR-07 | May | The system shall report metrics on express-path usage (count, average implementation time, classification breakdown) |

## Non-Functional Requirements

| ID | Requirement | Category |
|---|---|---|
| NFR-01 | The express path shall complete in fewer total tokens than the full pipeline for the same feature | Efficiency |
| NFR-02 | The express path shall not reduce code quality below the standard of the full pipeline; implementations must still pass normal CI checks | Quality |
| NFR-03 | The classification logic shall be configurable without code changes (e.g., via flows.yml or project settings) | Maintainability |
| NFR-04 | The express path must not break existing full-pipeline features; the two paths operate orthogonally | Compatibility |
| NFR-05 | The classification logic shall reject attempts to spoof eligibility via label manipulation on issues that do not meet the configured criteria | Security |

## Constraints

- The classification must work with the existing GitHub issue labels and the project's flows framework
- The express path must co-exist with the existing bug fix fast path without conflicting
- No new external services or dependencies may be introduced
- Artifacts produced by the express path must follow the same `.sdlc/` conventions as full-pipeline artifacts

## Acceptance Criteria

- [ ] **FR-01** (eligible classification)
    - **Given** an issue with labels indicating low complexity (e.g., no `llmaw:complex` label, scope is well-defined)
    - **When** the pipeline routes the issue
    - **Then** the issue is classified as eligible for the express path
- [ ] **FR-01** (ineligible classification)
    - **Given** an issue with labels or description indicating high complexity or cross-cutting scope
    - **When** the pipeline routes the issue
    - **Then** the issue is classified as ineligible and routed to the full pipeline
- [ ] **FR-01** (configurable criteria)
    - **Given** a configuration change in flows.yml or project settings
    - **When** the routing rules are updated
    - **Then** subsequent issues are classified according to the updated criteria
- [ ] **FR-02** (happy path)
    - **Given** a classified-eligible issue with a clear scope
    - **When** the express path runs
    - **Then** a PR is created with the implementation code (or a clear explanation of why automatic implementation is infeasible)
- [ ] **FR-02** (execution failure)
    - **Given** a classified-eligible issue
    - **When** the express path encounters an error during implementation
    - **Then** the error is reported to the issue with details, and no automatic fallback to the full pipeline occurs
- [ ] **FR-02** (no planning artifacts)
    - **Given** an eligible issue processed through the express path
    - **When** execution completes
    - **Then** no requirements, existing-solutions, codebase-analysis, feasibility, specifications, telemetry, observability, or plan artifacts exist for this feature
- [ ] **FR-03** (artifact trail)
    - **Given** an express-path execution
    - **When** it completes
    - **Then** a minimal artifact exists under `.sdlc/features/` recording the decision to use the express path and the outcome
- [ ] **FR-04** (fallback)
    - **Given** an ineligible issue
    - **When** the pipeline routes it
    - **Then** the full SDLC pipeline runs normally, starting from requirements
- [ ] **FR-05** (classification logging)
    - **Given** any issue processed through the pipeline
    - **When** classification runs
    - **Then** a comment or artifact records the classification decision and its rationale
- [ ] **FR-06** (override)
    - **Given** an eligible issue
    - **When** a human removes the express-path label
    - **Then** the issue is routed to the full pipeline on the next cycle
- [ ] **FR-06** (inverse override)
    - **Given** an ineligible issue
    - **When** a human adds the express-path label
    - **Then** the issue is routed to the express path on the next cycle
- [ ] **FR-07** (metrics reporting)
    - **Given** at least one feature has been processed through the express path
    - **When** metrics are queried
    - **Then** the response includes the count of express-path features and the average implementation time
- [ ] **FR-07** (classification breakdown)
    - **Given** at least one issue has been classified as eligible and one as ineligible
    - **When** metrics are queried
    - **Then** the response includes a breakdown of classifications

## Conflicts

<!-- Populated by /review-requirements. Leave as "None identified yet." when drafting. -->

None identified yet.

## Open Questions

1. What exactly qualifies as a "simple feature"? Should it be defined by label presence, issue body length, change scope (single file vs. multi-file), or a combination?
2. Should the express path produce a plan artifact that simply states "fast path: plan skipped"? Or should it produce zero artifacts (relying entirely on the PR description)?
3. How should metrics be exposed to the project owner? Via GitHub issue comments, a dashboard, or logs?
