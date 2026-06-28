---
issue: "#17"
title: "Implement directly from issue"
status: in-review
---

# Feasibility Assessment: Implement directly from issue

## Overview

This feature adds an express pipeline path that routes eligible issues directly from triage to implementation, skipping the 14+ planning phases. The goal is to reduce token consumption and delivery time for simple, well-understood features while maintaining an artifact trail for traceability. The codebase analysis confirms the express path reuses the existing engine infrastructure nearly unchanged — only `flows.yml` label definitions and the external triage-issue skill need extension. The primary risk is whether `create-implementation` can produce correct code without upstream planning artifacts.

## Technical Feasibility

| Criterion | Assessment |
|---|---|
| Required technologies | Available in-house — Python, YAML, GitHub Actions, existing flows engine |
| Integration complexity | Low — new express flow mirrors the existing bugfix fast path pattern |
| Technical risks | `create-implementation` without planning artifacts is untested; triage-issue skill lives in external repo requiring coordinated rollout; classification criteria for "simple feature" needs definition |
| Existing components to reuse | Engine core, route, run_rule, run_steps, apply_outcome, dispatch.yml, branch scripts, label syncer — all reuse as-is |

**Verdict:** Feasible with conditions

## Financial Feasibility

| Criterion | Assessment |
|---|---|
| Estimated effort | M — primarily configuration (flows.yml labels/rules) plus extending the triage-issue skill verdict schema; testing the express path end-to-end |
| Infrastructure costs | None — runs in existing GitHub Actions infrastructure |
| Third-party costs | None — no new external services or dependencies |
| ROI expectation | High — reduces token consumption and cycle time for every simple feature; unblocks the project's use as a full GitHub-centric workflow replacement |

**Verdict:** Feasible

## Operational Feasibility

| Criterion | Assessment |
|---|---|
| Team availability | Available — single maintainer project; changes are incremental |
| Skill gaps | None — flows.yml, engine patterns, and the SDLC pipeline are in-house knowledge |
| Maintenance burden | Low — additive labels and rules; express flow is orthogonal to existing feature/bugfix flows |
| Organizational alignment | Fits roadmap — directly supports the project owner's goal of replacing vibe-kanban with a pure GitHub workflow |

**Verdict:** Feasible

## Go/No-Go Decision

**Overall verdict:** Go with conditions

**Conditions (if any):**

- Spike to verify `create-implementation` works correctly without upstream planning artifacts (requirements, specifications). If the skill requires those artifacts, the express path must produce lightweight stubs or the eligibility criteria must be narrowed to features that need implementation only.
- Coordinate the triage-issue skill verdict extension (add `complexity` field) before or in lockstep with the express flow rules in `flows.yml`. The skill update and the flow config should ship in the same release window to avoid orphaned label states.

## Open Questions

1. Does `create-implementation` require `.sdlc/` planning artifacts to produce correct output, or can it work from the issue body alone for simple features?
2. Should express eligibility be decided inside the triage-issue skill (single pass) or as a separate rule after triage (two-pass, more modular)?
3. What minimal artifact format does the express path produce — a lightweight `.sdlc/` file, an issue comment, or a label?
4. What are the default three-tier complexity criteria (issue body length, change scope estimate, label presence, or combination)?
5. Should the manual override label be `llmaw:quick-implement` or a different name?
