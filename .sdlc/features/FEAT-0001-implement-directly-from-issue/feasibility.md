---
issue: "#17"
title: "Implement directly from issue"
status: approved
revision: 1
---

# Feasibility Assessment: Implement directly from issue

## Overview

This feature adds an express pipeline path that routes eligible issues directly from triage to implementation, skipping the 14+ planning phases. The goal is to reduce token consumption and delivery time for simple, well-understood features while maintaining an artifact trail for traceability. The codebase analysis confirms the express path reuses the existing engine infrastructure nearly unchanged — only `flows.yml` label definitions and the external triage-issue skill need extension. The primary risk is whether `create-implementation` can produce correct code without upstream planning artifacts.

## Assumptions

The following assumptions underpin this assessment. Each has a validation plan and is recorded for traceability.

| Assumption | Basis | Risk | Validation Plan |
|---|---|---|---|
| The flows engine can be extended with new express-flow rules without refactoring existing flow matching logic | engine.py is generic; it loads all rules from flows.yml and matches by `when` conditions independently | Low | Verify by adding a test rule to a local flows.yml fork and confirming existing feature/bugfix rules still match |
| The triage-issue skill extension can ship in the same release window as the flow config | Both changes are in separate repos but have no hard deployment ordering; the express rules check for `complexity: low` and gracefully degrade if absent | Medium | Define fallback: if triage-issue skill lacks `complexity` field, express rules simply never match; issues fall through to the feature flow (safe degradation) |
| The express path pattern mirrors the bugfix fast path cleanly without unforeseen interactions | bugfix flow (flows.yml:476-521) is an existing parallel fast path; express flow uses identical rule/label/outcome patterns | Low | Inspect flows.yml to confirm no overlapping `when:` conditions between express labels and bugfix/feature labels |
| `create-implementation` can produce correct output from the issue alone for simple features | This is the core premise of the express path; unverified | High | Condition 1 requires a spike to validate; if false, architecture forks (see Conditions) |

## Technical Feasibility

| Criterion | Assessment |
|---|---|
| Required technologies | Available in-house — Python, YAML, GitHub Actions, existing flows engine |
| Integration complexity | Low — new express flow mirrors the existing bugfix fast path pattern |
| Technical risks | `create-implementation` without planning artifacts is untested (high-impact, requires spike); triage-issue skill lives in external repo requiring coordinated rollout (see fallback below); classification criteria for "simple feature" needs definition |
| Existing components to reuse | Engine core, route, run_rule, run_steps, apply_outcome, dispatch.yml, branch scripts, label syncer — all reuse as-is |

**Fallback for external repo dependency gap:** If the triage-issue skill extension PR is not merged when the express flow config ships, the express labels remain inert — the `on_outcome` mapping simply never matches `complexity: low` (field absent). Issues proceed through the existing feature flow unchanged. No orphaned labels or broken state. The express path activates only after both sides of the contract are deployed.

**Verdict:** Feasible with conditions

## Financial Feasibility

| Criterion | Assessment |
|---|---|
| Estimated effort | M (3–5 days): 1 day for flows.yml labels/rules, 1 day for triage-issue skill verdict extension, 1 day for spike to verify `create-implementation`, 1–2 days for end-to-end testing and documentation |
| Infrastructure costs | None — runs in existing GitHub Actions infrastructure |
| Third-party costs | None — no new external services or dependencies |
| ROI expectation | Conditionally high — reduces token consumption and cycle time for every simple feature, but final ROI depends on spike outcome. If spike confirms `create-implementation` works from issue alone, ROI is high. If lightweight stubs are needed, token savings are partially eroded. |

**Verdict:** Feasible

## Operational Feasibility

| Criterion | Assessment |
|---|---|
| Team availability | Available — single maintainer project; changes are incremental |
| Skill gaps | Low uncertainty — flows.yml, engine patterns, and SDLC pipeline are in-house knowledge, but `create-implementation` behavior without planning artifacts is uncharacterized. If spike reveals the skill needs non-trivial modification, additional skill-internals knowledge is required. |
| Maintenance burden | Low — additive labels and rules; express flow is orthogonal to existing feature/bugfix flows |
| Organizational alignment | Fits roadmap — directly supports the project owner's goal of replacing vibe-kanban with a pure GitHub workflow |

**Verdict:** Feasible with conditions

## Go/No-Go Decision

**Overall verdict:** Go with conditions

**Conditions (if any):**

1. **Spike: verify `create-implementation` without planning artifacts.**
   - **Timeline:** 1 day.
   - **Exit criteria:** Run `create-implementation` on a simple feature issue with no `.sdlc/` upstream artifacts. If the output is a correct, buildable implementation, spike passes. If the skill errors or produces nonsensical output, the express path must either (a) produce lightweight stub artifacts before running implementation, or (b) narrow eligibility to features that need implementation-only changes.
   - **Fallback on failure:** Use option (a) — generate stubs with issue body as sole context. This adds ~0.5 day effort and reduces token savings by ~20%.

2. **Coordinate triage-issue skill verdict extension.**
   - **Timeline:** The skill extension PR should be merged before or concurrently with the express flow config.
   - **Exit criteria:** The `triage-issue` skill emits a `complexity` field (low/medium/high) in its verdict. The express flow's `on_outcome` gracefully handles absence of the field.
   - **Fallback on failure:** Labels not created; express flow inactive until skill is updated. Issue proceeds through the feature flow normally.

## Reversibility

The express path changes are mostly additive (new labels, new flow rules, new verdict field). The path can be cleanly backed out by:
- Removing the express flow labels from the issue (labels revert to feature flow)
- Reverting the `flows.yml` express block
- The triage-issue skill `complexity` field is additive; existing consumers ignore it after revert

**One-way door:** The `complexity` field in the triage-issue skill verdict creates mild coupling between the skill (external repo) and the express flow rules. Once both are deployed, reverting the field from the skill means all consuming rules must also revert. This is a low-risk one-way door because the field is optional and express rules gracefully degrade when absent.

**Rollback strategy:** If the express path causes problems in production (incorrect implementations, classification errors):
- Remove the express-eligibility labels from all affected issues
- Comment on the issue to route back through the feature flow
- Revert the flows.yml express block (single PR)

## Open Questions

1. Does `create-implementation` require `.sdlc/` planning artifacts to produce correct output, or can it work from the issue body alone for simple features?
2. Should express eligibility be decided inside the triage-issue skill (single pass) or as a separate rule after triage (two-pass, more modular)?
3. What minimal artifact format does the express path produce — a lightweight `.sdlc/` file, an issue comment, or a label?
4. What are the default three-tier complexity criteria (issue body length, change scope estimate, label presence, or combination)?
5. Should the manual override label be `llmaw:quick-implement` or a different name?
