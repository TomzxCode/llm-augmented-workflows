---
issue: "#18"
title: "Support other CLI tools"
status: approved
---

# Needs Assessment: Support Other CLI Tools

## Problem Statement

The LLM-Augmented Workflows engine currently hardcodes `opencode` as the sole AI agent runtime for executing skill steps. Users who prefer or are required to use alternative AI CLI tools (Codex CLI, Gemini CLI, Claude Code) cannot use them within the workflow engine, limiting adoption and forcing tool choice rather than enabling it.

## Stakeholders

| Stakeholder | Role | How they experience the problem |
|---|---|---|
| Workflow consumers | user | Must use opencode as the AI runtime even if their team or policy dictates another tool |
| Project maintainer | admin | Cannot offer the engine to teams with constraints on which AI CLI they can run |
| Tool-evaluating teams | business | Must commit to opencode before evaluating the engine's value proposition |

## Evidence of Need

| Source | What it shows | Strength |
|---|---|---|
| Issue #18 (single feature request) | Lists "Codex, OpenCode, Gemini, etc." as desired CLI tool support | Weak |
| No user requests, support tickets, or usage data | No demonstrated demand beyond the issue author | None |

**Evidence rating:** Weak

The need is assumed rather than demonstrated. The single brief issue lists tool names without describing specific pain, use cases, or adoption barriers. No evidence exists that users are blocked or that the lack of multi-tool support has caused anyone to abandon the project.

## Cost of Inaction

| Aspect | Impact |
|---|---|
| What breaks or degrades today | Nothing breaks. The engine works correctly with opencode. |
| Existing workarounds | Users can run arbitrary CLI tools via `shell` steps in the pipeline, at the cost of losing native verdict/outcome integration. |
| Trend | Growing -- more AI CLI tools are emerging, so the limitation may become more salient over time. |

**Cost-of-inaction rating:** Weak

The status quo is fully functional. No reports of significant pain or lost adoption due to the single-runtime constraint.

## Alternative Paths

| Alternative | How it addresses the need | Trade-offs |
|---|---|---|
| Shell steps for other tools | Users can invoke any CLI via `shell` steps in `flows.yml` | No native verdict parsing, no outcome integration, no skill abstraction. Requires manual glue code. |
| Document multi-tool integration | Explain how to wrap alternative CLIs in shell steps with custom outcome handling | Same trade-offs as shell steps, plus documentation maintenance cost. |

**Could the need be met without new code?** Partially

Shell steps already allow running any CLI tool. The gap is the loss of structured verdict/outcome integration that the `opencode` agent step provides. New code would be needed to abstract the agent step behind a generic interface that supports multiple CLI runtimes with consistent output handling.

## Strategic Alignment

| Criterion | Assessment |
|---|---|
| Aligns with project goals | Partially -- the project aims to provide a flexible automation engine, but multi-tool support is not an explicit goal |
| Serves core or edge use case | Edge -- the agent step is core, but swapping the runtime is an operational concern, not a functional one |
| Dependency enabler | Unblocks 0 other features; no downstream feature depends on this |

**Alignment rating:** Moderate

Broadening runtime support could increase adoption but the project's primary value (config-driven pipeline, state machine, outcome handling) does not depend on which AI CLI executes the skill.

## Verdict

**Overall needs assessment:** Nice-to-have

**Rationale:** The request addresses a legitimate flexibility gap but the evidence of need is weak (single brief issue, no usage data or user demand), the cost of inaction is low (shell steps provide a partial workaround), and strategic alignment is moderate. The feature would improve adoption breadth but is not essential for the engine's core value proposition.

## Conditions to Proceed

- Evidence of demand from multiple users or teams requesting specific alternative CLI tools.

## Open Questions

1. Which specific CLI tools (beyond opencode) are most requested, and what are their runtime requirements (installation, permissions, output format)?
2. Is there actual user demand beyond the issue author, or is this a speculative enhancement?
3. What is the engineering effort to abstract the agent step vs. the expected adoption benefit?
