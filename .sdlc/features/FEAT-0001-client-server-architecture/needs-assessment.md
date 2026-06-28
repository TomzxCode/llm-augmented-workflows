---
issue: "#16"
title: "Client/Server architecture"
status: approved
---

# Needs Assessment: Client/Server architecture

## Problem Statement

The current engine runs entirely within GitHub Actions runners: it is stateless, invoked per-event via workflows, and must check out the full engine repository on every execution. This creates dependency on GitHub runner availability, cold-start latency on each invocation, no persistent runtime state between events, and limited control over the execution environment. The underlying problem is that a stateless runner-based model may not scale to more complex, stateful agent interactions or meet reliability requirements for production use.

## Stakeholders

| Stakeholder | Role | How they experience the problem |
|---|---|---|
| Project users / adopters | Developer | Depend on GitHub Actions uptime and quotas for the automation pipeline; no persistent agent state between events |
| Project maintainer | Developer | Must manage engine distribution via GitHub checkout; limited observability into agent execution outside GitHub logs |
| Downstream repo owners | Developer | Must configure GitHub Actions workflows and accept the associated cost and latency |

## Evidence of Need

| Source | What it shows | Strength |
|---|---|---|
| Issue #16 author proposal | Suggests moving to hosted server with webhooks and persistent state | Weak |
| User requests / support tickets | None documented | None |
| Usage data | No usage data available (project is v0.1.0) | None |
| Competitive analysis | Similar tools (e.g., opencode itself) can be run as persistent agents | Moderate |

**Evidence rating:** Weak

The need is assumed rather than demonstrated. No users have reported issues with the current GitHub Actions-based model, and the project has no production deployment data to surface scaling or reliability problems.

## Cost of Inaction

| Aspect | Impact |
|---|---|
| What breaks or degrades today | Nothing breaks. The current stateless runner model is functional by design. |
| Existing workarounds | Users can run agents locally, use self-hosted runners, or optimize workflow caching. These address runtime control and latency without a server architecture. |
| Trend | Stable. The current architecture is not regressing. |

**Cost-of-inaction rating:** Weak

The status quo is tolerable and intentionally designed. No known pain points drive urgency.

## Alternative Paths

| Alternative | How it addresses the need | Trade-offs |
|---|---|---|
| Self-hosted GitHub Actions runners | Provides control over execution environment and reduces cold-start latency | Still stateless per-run; requires runner management; does not enable persistent agent state |
| GitHub Actions caching + optimized checkout | Reduces checkout/reprovisioning overhead | Does not address architectural constraints around state or server-side control |
| Local agent execution (developer machines) | Full control, persistent state possible | Not automated; does not scale to team or CI use |
| Keep current architecture | Simple, well-understood, zero infrastructure cost | Does not address the (unvalidated) concerns about scaling or state |

**Could the need be met without new code?** Yes

Self-hosted runners and caching optimizations address the execution environment concerns. Persistent agent state would require new code, but no evidence shows this is needed yet.

## Strategic Alignment

| Criterion | Assessment |
|---|---|
| Aligns with project goals | Partially. The project goal is a "config-driven automation engine for GitHub." The current design achieves this. A server model shifts toward a hosted-platform model with different operational costs and ownership. |
| Serves core or edge use case | Edge. The current model serves the core use case. The server model would enable scenarios (multi-tenant, persistent agents) beyond the current scope. |
| Dependency enabler | Moderate. If adopted, it would enable stateful agent interactions and centralized observability, unlocking more complex automation flows. |

**Alignment rating:** Moderate

## Verdict

**Overall needs assessment:** Nice-to-have

**Rationale:** The proposed architectural shift is technically interesting and could unlock future capabilities (persistent agents, centralized management), but there is no evidence that users are hitting limitations of the current model. The project is at v0.1.0 with no documented pain points. Investing in a client/server architecture before validating that the current runner-based model is insufficient risks premature complexity and infrastructure cost. The feature should be revisited when user adoption surfaces concrete limitations.

## Conditions to Proceed

- User adoption reveals concrete limitations of the current GitHub Actions-based model (quota exhaustion, reliability issues, demand for persistent state).
- At least 3 independent users or teams adopt the engine and report a shared constraint that cannot be addressed by self-hosted runners or caching.

## Open Questions

1. What specific limitations of GitHub Actions runners have users encountered (if any)?
2. Is persistent agent state a real requirement for the expected use cases, or is stateless event-driven automation sufficient?
3. What is the operational cost tolerance for maintaining a hosted server versus the current zero-infrastructure model?
