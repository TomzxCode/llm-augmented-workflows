---
issue: "#16"
title: "Client/Server architecture"
status: in-review
revision: 2
---

# Feasibility Assessment: Client/Server architecture

## Overview

Replace the GitHub Actions execution model with a hosted HTTP server that receives GitHub webhook events, maintains persistent session state via SQLite, and orchestrates agent execution server-side. The existing agent pipeline (`engine.py`, `route.py`, `run_rule.py`, `run_steps.py`, `apply_outcome.py`) is refactored to accept context as function parameters instead of environment variables, enabling both the new server path and the existing CLI path. Repos that adopt the architecture no longer need GitHub Actions workflows or checkout the engine repository per-event. The feature is being considered because the current stateless-runner model ties execution to GitHub runner availability and checkout latency, though no users have reported hitting these limits (see needs-assessment verdict: "nice-to-have").

## Technical Feasibility

| Criterion | Assessment |
|---|---|
| Required technologies | Available in-house (Python, GitHub API, stdlib hmac) + New (FastAPI, Uvicorn, aiosqlite, Docker) |
| Integration complexity | Medium |
| Technical risks | Skill file distribution strategy unresolved; concurrent multi-repo env var racing resolved via parameter injection; retry logic must not mask permanent failures; incorrect HMAC implementation could allow unauthorized webhook requests; GitHub at-least-once webhook delivery requires idempotency handling (dedup via `X-GitHub-Delivery` header); SQLite serializes writes — concurrent write contention under 10-repo load (NFR-04); `run_in_executor` threading assumes GIL contention and thread pool exhaustion are acceptable under NFR-04 load |
| Existing components to reuse | `engine.py` (reuse as-is), `cli.py` (reuse as-is), `sync_labels.py` (reuse as-is), refactored `route.py`/`run_rule.py`/`run_steps.py`/`apply_outcome.py` with backward-compatible wrappers |

The core engine (`engine.py`) is pure functions with no I/O side effects — reuse as-is. The pipeline entry points need mechanical refactoring (extract logic into parameterized functions, keep CLI wrappers). The new server components (FastAPI routes, HMAC verification, SQLite session store) are standard patterns with zero licensing risk. HMAC verification must follow GitHub's reference implementation using `hmac.compare_digest` for timing-safe comparison; any deviation is a security risk and must be caught in code review. Webhook idempotency must be handled via `X-GitHub-Delivery` header deduplication. SQLite concurrent write contention under NFR-04 load requires a lightweight lock or queue (e.g., `asyncio.Lock` per repo); migration to PostgreSQL is the escalation path if contention becomes blocking. Thread pool sizing must account for GIL-bound pipeline steps — the server should use a bounded thread pool (e.g., `ThreadPoolExecutor(max_workers=20)`) to prevent exhaustion under NFR-04's 10 concurrent repos.

Two open questions remain: how skill files are distributed in the Docker image (cloned at start, mounted, or fetched on first use), and whether the server needs a `FORCE_RULE_ID` bypass. Neither blocks the feasibility decision — the first has multiple viable approaches that can be decided during implementation, the second is trivially addable. The skill distribution strategy is moved to a condition below to ensure it is resolved before implementation begins.

**Verdict:** Feasible

## Financial Feasibility

| Criterion | Assessment |
|---|---|
| Estimated effort | L |
| Infrastructure costs | Low — single VM or Docker host (e.g., $10-30/month for a cloud VPS or existing CI runner repurposed) |
| Third-party costs | Zero — all dependencies (FastAPI, Uvicorn, aiosqlite, httpx) are MIT/BSD-licensed open source. No SaaS or API usage fees beyond existing LLM API and GitHub API costs. |
| ROI expectation | Moderate — unlocks stateful agent interactions, centralized observability, and eliminates per-repo workflow configuration. But the current zero-infrastructure model works and the needs-assessment found no documented user demand. The investment (weeks of refactoring + new server code + Docker image) trades infrastructure cost for engineering cost before the need is validated. |

The effort is L because the refactoring touches four modules with behavioral-identity constraints, the server requires greenfield development across six sub-components (webhook receiver, session store, registration store, pipeline bridge, admin API, Dockerfile), and the retry and env var isolation changes must be validated against the full acceptance criteria suite. Infrastructure costs are negligible (a single VM). Third-party costs are zero. The ROI hinges on whether the unlocked capabilities (persistent state, centralized mgmt) justify the upfront engineering cost at this project stage.

**Conditions:** None — no financial barriers.

**Verdict:** Feasible

## Operational Feasibility

| Criterion | Assessment |
|---|---|
| Team availability | Partially — project is v0.1.0, likely a solo maintainer or small team. The refactoring and server work is additive to existing responsibilities. |
| Skill gaps | Async Python (FastAPI, Uvicorn, aiosqlite, asyncio) is not used in the current codebase. The maintainer must either learn these or the refactoring plan must minimize async surface area (synchronous pipeline wrapped via `run_in_executor`). |
| Maintenance burden | Medium — the server adds a new runtime component (Docker image, state persistence, webhook endpoint) with its own operational concerns (restart, crash recovery, log rotation, TLS termination). The existing CLI path is preserved but must not regress. Two parallel execution paths increase testing surface. |
| Organizational alignment | Tangential — the project's stated goal is a "config-driven automation engine for GitHub." The server model shifts toward a hosted-platform model with different operational demands. The current GitHub Actions model fully delivers the value proposition. |

The primary operational risk is solo-maintainer bandwidth: the feature requires weeks of focused work across the full stack (refactoring, new async code, Docker, testing) while keeping the existing path working. The async skill gap can be mitigated by keeping the server's async surface minimal (webhook receiver only, pipeline dispatched via `run_in_executor`). The maintenance burden is real but low in absolute terms for a single-container deployment.

**Conditions:** The implementer must produce an operational runbook covering restart, log rotation, crash recovery, TLS termination, volume backup, and rollback before the server is deployed to production. The preserved CLI path provides implicit rollback: if the server model proves unsustainable, repos revert to the GitHub Actions workflow path with no code changes.

**Verdict:** Feasible with conditions

## Go/No-Go Decision

**Overall verdict:** Go with conditions

**Conditions (if any):**

- The async skill gap must be addressed before implementation begins: either the implementer has production FastAPI experience, or the refactoring plan explicitly minimizes async surface area (sync pipeline wrapped via `run_in_executor`).
- Skill file distribution strategy for the Docker image must be decided before server implementation (options: clone at startup, mount as volume, fetch on first use).
- An operational runbook covering restart, log rotation, crash recovery, TLS termination, volume backup, and rollback must be drafted before the server is deployed to production.

## Open Questions

1. Should the server distribute skill files by cloning the agent repository at container startup (simplest, cold-start latency) or by bundling them in the Docker image (faster startup, rebuild on skill change)?
2. Does the maintainer have the bandwidth for an L-size feature at this project stage (v0.1.0, no validated user demand for a server model)?
3. Should SQLite concurrent write contention be mitigated with per-repo `asyncio.Lock` or with a migration path to PostgreSQL as an escape hatch?
