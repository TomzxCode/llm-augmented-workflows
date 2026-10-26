---
issue: "#18"
title: "Support other harness CLI"
status: approved
---

# Needs Assessment: Support Other Harness CLI

## Problem Statement

The engine can only invoke `opencode` as its agent step. Users who prefer or require a different AI agent runtime (Codex CLI, Gemini CLI, Claude Code, etc.) must either fork the engine or use the `shell` step, which lacks native outcome/verdict integration — they cannot participate in the label-driven state machine without custom scripting.

## Stakeholders

| Stakeholder | Role | How they experience the problem |
|---|---|---|
| Flow authors / workflow consumers | User | Cannot select a non-opencode AI runtime as the agent step; must use `shell` steps without verdict routing |
| Project maintainers | Developer | Must maintain and extend a single-agent architecture; adding runtime-specific features (e.g., model config, timeout handling) is coupled to opencode |
| Security / compliance | Admin | If an org mandates a specific AI tool (e.g., for data residency or audit), the engine cannot comply without customization |
| Ops / infrastructure | Admin | Each supported runtime may need different installation, auth, or sandboxing; the current uniform install (curl + bash) assumes opencode |

## Evidence of Need

| Source | What it shows | Strength |
|---|---|---|
| Issue #18 (this issue) | Lists three CLIs but provides no use case, user stories, or supporting data | Weak |
| GitHub issues / discussions | No other user requests or support tickets for multi-runtime support found | None |
| Competitive analysis | Similar workflow engines (e.g., Probot, StackStorm) support plugin-based executors; not having this limits parity | Moderate |
| Usage data | No data available on users switching away due to missing runtime support | None |

**Evidence rating:** Weak

The need is assumed rather than demonstrated. There is no data showing users are blocked or that adoption is limited by single-runtime support. The competitive analysis angle suggests directional value, not current demand.

## Cost of Inaction

| Aspect | Impact |
|---|---|
| What breaks or degrades today | Nothing breaks. The engine works correctly with opencode. |
| Existing workarounds | Users can invoke other CLIs via the `shell` step (e.g., `shell: codex -f prompt.txt`). This bypasses the outcome/verdict system — the engine cannot route on the agent's verdict, relabel, or close issues based on the result. Every rule using a non-opencode agent must reimplement verdict routing in shell scripts. |
| Trend | Stable. No evidence that demand is growing or that users are churning. |

**Cost-of-inaction rating:** Weak

The status quo is tolerable. Workarounds exist at a moderate ergonomic cost (lost verdict integration), but no operational or user-facing degradation is occurring.

## Alternative Paths

| Alternative | How it addresses the need | Trade-offs |
|---|---|---|
| Document shell-step pattern for other CLIs | Shows users how to run any CLI via `shell` steps and parse its output into labels/comments manually | No native verdict routing; each flow reimplements the same boilerplate; no support matrix or lifecycle management |
| Plugin/extension model for agent executors | A future architecture change could make the agent step pluggable | Higher up-front investment; speculative without evidence of demand |
| Third-party tool (e.g., n8n, Temporal) | These platforms support multiple AI executors natively | Complete platform migration; not proportional to the stated need |

**Could the need be met without new code?** Partially

The `shell` step can run any CLI today. The missing piece is native outcome/verdict integration for non-opencode runtimes. A documentation-only change would address the "I want to use Tool X" use case but not the "I want Tool X to participate in the label state machine" use case.

## Strategic Alignment

| Criterion | Assessment |
|---|---|
| Aligns with project goals | Partially — the project's stated goal is a "config-driven automation engine." Being tool-agnostic aligns with broad adoption, but the engine is explicitly described as "powered by opencode" and the current design assumes a single agent runtime. No project-overview.md exists in `.sdlc/context/`; goals are inferred from README. |
| Serves core or edge use case | Edge — the core use case (trigger opencode skills via GitHub events) works fully today. Multi-runtime support extends this to adjacent workflows. |
| Dependency enabler | Unblocks 0 other features. No downstream phase in the SDLC pipeline requires multi-runtime support. |

**Alignment rating:** Weak

The feature is tangentially aligned. It broadens the engine's addressable audience but does not advance the current stated purpose (driving opencode-based SDLC workflows).

## Verdict

**Overall needs assessment:** Nice-to-have

**Rationale:** The request to support multiple AI agent runtimes has intuitive appeal (tool flexibility, future-proofing) but lacks demonstrated demand, usage data, or a clear cost of inaction. The existing `shell` step provides a partial workaround at the cost of verdict integration. Without evidence that users are blocked or that adoption is limited, investing in multi-runtime support is premature. The need should be revisited when user demand materializes (support tickets, lost deals, explicit requests from downstream consumers).

## Conditions to Proceed

- Evidence of demand from at least 2 external users or teams (e.g., GitHub issues, support tickets, community discussion) within a 3-month window, demonstrating that the `shell` workaround is insufficient or that a specific runtime is required by organizational policy.

## Open Questions

1. Which specific CLI(s) beyond opencode are users requesting, and what workflow do they need them for?
2. What is the minimum integration surface for a "supported runtime" — is a configurable `agent.command` template sufficient, or does each runtime need custom lifecycle management (install, auth, timeout, verdict parsing)?
3. Does the project want to be a polyglot agent runtime orchestrator, or should it remain an opencode-specific engine with a `shell` escape hatch?
