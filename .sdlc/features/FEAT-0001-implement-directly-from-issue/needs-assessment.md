---
issue: "#17"
title: "Implement directly from issue"
status: approved
---

# Needs Assessment: Implement directly from issue

## Problem Statement

The current feature pipeline forces every feature through a 14+ phase SDLC chain (triage, needs, requirements, existing-solutions, codebase-analysis, feasibility, specifications, telemetry, observability, plan, tasks, tests, implementation). For simple, well-understood features where the scope is clear from the issue description alone, this full pipeline adds unnecessary overhead, delays delivery, and consumes tokens on planning artifacts that add little value. The project owner wants to rely entirely on GitHub (replacing a separate kanban tool) and needs an express path from issue to implementation PR for simple features.

## Stakeholders

| Stakeholder | Role | How they experience the problem |
|---|---|---|
| Project owner (tomzx) | Maintainer / Developer | Must wait through the full pipeline even for trivial features; cannot use this project as a full GitHub-centric workflow replacement |
| Contributors | Developer | Subject to the same overhead for simple contributions; may find the pipeline too heavy for small changes |
| LLM agent | Automation | Spends tokens generating artifacts for features where the path is already clear |

## Evidence of Need

| Source | What it shows | Strength |
|---|---|---|
| Feature request by project owner | The owner explicitly requests a skip-plan path and expresses desire to replace vibe-kanban with a pure GitHub workflow | Strong (owner-authored) |
| Existing bug fix pipeline | The project already implements a fast path for bugs (skipping all feature phases), proving the pattern is viable | Moderate |
| Usage data | None yet; the project is pre-production | None |

**Evidence rating:** Moderate

The primary evidence is the project owner's explicit feature request. The bug fix pipeline provides structural precedent but no usage data exists yet. The need is real but the frequency and nature of features that would qualify for the fast path are not yet quantified.

## Cost of Inaction

| Aspect | Impact |
|---|---|
| What breaks or degrades today | Every feature must traverse the full pipeline, including simple one-change features |
| Existing workarounds | File features as bugs to use the shorter bug fix pipeline; manually implement features outside the automation system |
| Trend | Growing — as the project is adopted, more simple features will be proposed; the overhead compounds |

**Cost-of-inaction rating:** Moderate

The pipeline is usable today, so nothing is broken. But the overhead discourages using the automation for quick changes and undermines the goal of replacing a kanban tool with a pure GitHub workflow.

## Alternative Paths

| Alternative | How it addresses the need | Trade-offs |
|---|---|---|
| File features as bugs | Bypasses the feature pipeline entirely via the bug fix path | Misuses the bug label; loses feature tracking and artifact trail |
| Manual implementation outside the automation | Delivers the code without pipeline overhead | Loses consistency, audit trail, and automation benefits |
| Add labels to skip individual phases | Allows selective skipping of specific steps | Adds complexity to flows.yml; still requires some pipeline traversal |

**Could the need be met without new code?** Partially

Existing workarounds exist but each has significant trade-offs. A proper "implement directly" path is the clean solution.

## Strategic Alignment

| Criterion | Assessment |
|---|---|
| Aligns with project goals | Yes — the project aims to provide flexible, configurable GitHub automation; a fast path directly supports that goal |
| Serves core or edge use case | Core — the ability to vary pipeline depth based on feature complexity is essential for practical adoption |
| Dependency enabler | Unblocks the project's use as a full GitHub-centric workflow (replacing external kanban) |

**Alignment rating:** Strong

## Verdict

**Overall needs assessment:** Needed

**Rationale:** The need is clearly articulated by the project owner, aligns directly with the project's strategic goals, and has structural precedent in the existing bug fix fast path. While usage data is absent (pre-production project), the project owner's explicit demand and the strategic importance of flexible pipeline depth make this a clear need. The Moderate evidence rating is offset by Strong strategic alignment and a non-trivial cost of inaction for the project's adoption as a full GitHub workflow replacement.

## Conditions to Proceed

- None — the need is clearly established by the project owner

## Open Questions

1. What criteria should distinguish a "simple feature" eligible for the fast path from a "complex feature" requiring the full pipeline?
2. Should the fast path require a human-applied label (e.g., `llmaw:quick-implement`) or should the triage agent decide?
3. What artifact trail (if any) should the fast path produce for traceability?
4. How many features in the existing issue tracker would qualify for the fast path? Usage data is absent; understanding frequency would strengthen the evidence base.
