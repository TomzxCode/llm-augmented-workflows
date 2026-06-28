---
issue: "#16"
title: "Client/Server architecture"
status: draft
---

# Existing Solutions: Client/Server architecture

## Overview

The feature requires a hosted HTTP server that receives GitHub webhook events, verifies HMAC-SHA256 signatures, maintains persistent session state, and dispatches events to the existing agent pipeline. No single off-the-shelf solution covers all requirements, but the key building blocks have mature open-source candidates. The recommended direction is a hybrid build: adopt FastAPI for the HTTP/ASGI layer and stdlib SQLite for session persistence, build the webhook-to-pipeline bridge around the existing engine.py and run_rule.py code, and borrow verification patterns from GitHub's own reference implementation and the WebhookWhisper guides.

## Search Scope

| Source | Searched | Notes |
|---|---|---|
| Internal codebase | Yes | No existing HTTP or webhook infrastructure. Agent pipeline (`engine.py`, `run_rule.py`, `route.py`) is reusable as-is. |
| Open-source | Yes | Python web frameworks (FastAPI, Starlette, Flask, stdlib http.server), ASGI servers (Uvicorn, Hypercorn), session storage (SQLite stdlib, aiosqlite), webhook verification libraries (py-webhook, webhook-guardian), agent task servers (Meerkat, opencode serve) |
| Commercial / SaaS | Yes | Svix, Hook0, Hookdeck, HookBytes — webhook infrastructure platforms. Overkill for a single-server deployment. |
| Standards / protocols | Yes | GitHub webhook protocol (HMAC-SHA256 via X-Hub-Signature-256), ASGI spec, GitHub REST API v3 |
| Reference material | Yes | GitHub docs on webhook validation, WebhookWhisper Python receiver guide, HookRay HMAC guide, Stripe webhook best practices |

## Candidate Solutions

| Solution | Type | License | Maturity | Covers | Gaps |
|---|---|---|---|---|---|
| FastAPI + Uvicorn | Library (framework + server) | MIT / BSD-3 | Mature | FR-01, FR-06, FR-07, FR-09, NFR-03, NFR-04 | FR-02 (needs session store), FR-03 (needs registration logic), FR-04 (needs agent bridge), NFR-01 (needs HMAC impl) |
| Starlette + Uvicorn | Library (toolkit + server) | BSD-3 | Mature | FR-01, FR-06, FR-07, NFR-03, NFR-04 | Same gaps as FastAPI, plus no auto-docs, no built-in validation |
| Flask + Gunicorn | Library (framework + server) | BSD-3 | Very mature | FR-01, FR-06 | No native async, WSGI limits (no WebSocket future), heavier concurrency model |
| Python stdlib `http.server` | Built-in | PSF | Mature | FR-01 (basic) | No routing, no middleware, single-threaded, production-unfit |
| SQLite (`sqlite3` stdlib) | Built-in | Public domain | Mature | FR-02 (session persistence), NFR-05, NFR-07 | No built-in async; needs `aiosqlite` for non-blocking access |
| `hmac` stdlib | Built-in | PSF | Mature | NFR-01 (signature verification) | None (trivially implements GitHub webhook verification) |
| py-webhook | Library | MIT | Nascent (0 stars) | NFR-01 | Immature, trivially replaced by stdlib hmac |
| webhook-guardian | Library | MIT | Nascent (1 star) | NFR-01 | Same as above |
| Meerkat | Product | MIT | Active | Agent task API with webhooks | Different scope (scheduled tasks, not GitHub event-driven); would need heavy adaptation |
| opencode serve | Built-in | Apache-2.0 | Mature | Server mode for agent | Designed for local IDE integration, not GitHub webhook receiving |
| Svix / Hook0 / Hookdeck | SaaS | Proprietary / SSPL | Mature | Webhook ingestion, delivery, retries | NFR-07 violation (external dependency), overkill for single-container model |

## Evaluation

### FastAPI + Uvicorn

- **Strengths:** Async-native, automatic OpenAPI documentation via Pydantic, built-in `BackgroundTasks` for dispatching agent work without blocking the webhook response, lifespan events for startup/shutdown, first-class support for request body access before JSON parsing (critical for HMAC verification). Uvicorn provides production-grade ASGI serving with graceful shutdown (`FR-07`).
- **Weaknesses:** Adds ~2 MB of dependencies (FastAPI + Starlette + Pydantic + Uvicorn). Requires async code paths (the existing engine is synchronous). The engine's `run_rule` and `_run_agent` are blocking calls and must be wrapped in `run_in_executor` to avoid blocking the event loop.
- **Integration effort:** Low to medium. Add `fastapi` and `uvicorn` via `uv add`. The existing CLI entry points in `cli.py` can be refactored into callable Python functions called from route handlers.
- **Cost:** Zero (MIT/BSD licensed).
- **Risks:**
  - **License:** None (MIT/BSD).
  - **Maintenance:** FastAPI and Uvicorn are well-maintained with frequent releases.
  - **Security:** Pydantic v2 is actively maintained; no known vulnerabilities.
  - **Lock-in:** Low. The webhook handler logic is independent of the framework; switching to Starlette or a minimal ASGI app later is straightforward.
- **Forward compatibility:** Both FastAPI and Uvicorn follow semver. The dependency surface is narrow (Pydantic for validation, Starlette for routing, Uvicorn for serving). Upgrades are typically additive.

### SQLite (stdlib + aiosqlite)

- **Strengths:** Zero-dependency, serverless, single-file database. Meets NFR-07 (no external runtime deps). SQLite's WAL mode supports concurrent reads while a write is in progress, sufficient for the target load (10 repos, ~1 event/sec each). Full SQL for querying session state.
- **Weaknesses:** Not designed for high-concurrency writes. Single-writer at a time may become a bottleneck under higher loads. No built-in async driver; needs `aiosqlite` for non-blocking access from the async event loop.
- **Integration effort:** Low. `sqlite3` is in stdlib. Add `aiosqlite` via `uv add`. Session schema is straightforward.
- **Cost:** Zero.
- **Risks:**
  - **Lock-in:** None (portable SQL, file-based).
  - **Performance:** At the target load (10 repos, ~1 event/sec), SQLite handles it comfortably. The session data per repo is small (conversation history as JSON blobs). If load grows 10x, migration to PostgreSQL is a schema-compatible change.
- **Forward compatibility:** SQLite format is stable across Python versions. Moving to PostgreSQL later is a driver swap with minor SQL dialect adjustments.

### GitHub Webhook HMAC Verification (stdlib `hmac`)

- **Strengths:** Reference implementation from GitHub docs. Uses `hmac.compare_digest` for timing-safe comparison. The pattern is well-documented and battle-tested.
- **Weaknesses:** Must access raw request body before any parsing. FastAPI supports this via `await request.body()`.
- **Integration effort:** Minimal. ~10 lines of Python.
- **Cost:** Zero.
- **Risks:** None. This is the canonical approach.

### Existing Internal Code (`engine.py`, `run_rule.py`, `route.py`)

- **Strengths:** The agent pipeline (load flows, match rules, run steps, apply outcomes) is already implemented and tested. Reusing it directly satisfies the constraint "must use the same agent/prompt logic as the existing engine." The data models (`Rule`, `When`, `Step`, etc.) are proven.
- **Weaknesses:** The pipeline expects environment variables (`GITHUB_EVENT_NAME`, `GITHUB_EVENT_PATH`) for context. The server must construct this context from the webhook payload. `_run_agent()` shells out to `opencode` CLI — this must continue to work in the container context.
- **Integration effort:** Medium. The server wraps `run_rule.py`'s logic with webhook-derived context instead of GitHub Actions environment variables. The `opencode` binary must be installed in the Docker image.
- **Cost:** Zero (already owned).
- **Risks:** Low. This is the core constraint of the feature.

### Flask + Gunicorn

- **Strengths:** Extremely well-known, extensive ecosystem, simple to get started.
- **Weaknesses:** Synchronous by default. The agent calls (`_run_agent` which runs `opencode`) are blocking and IO-heavy. With Flask, each request consumes a worker thread for the entire duration of the agent execution. Gunicorn's pre-fork model means each worker serves one repo/session at a time. At 10 repos, this requires at least 10 workers, each holding a full process image. No native async for future WebSocket support.
- **Integration effort:** Medium.
- **Cost:** Zero (BSD licensed).
- **Risks:** Scalability under concurrent webhook loads is worse than the async model. Graceful shutdown is harder to implement correctly (SIGTERM handling in Gunicorn vs Uvicorn's native lifespan).
- **Verdict:** Inferior to FastAPI for this use case. Not recommended.

### Starlette + Uvicorn (without FastAPI)

- **Strengths:** Lighter dependency than FastAPI (no Pydantic dependency if not used). Same ASGI performance.
- **Weaknesses:** Loses automatic OpenAPI documentation, Pydantic validation, dependency injection, `BackgroundTasks` convenience. These are all valuable for the admin REST API (FR-09). The dependency savings are marginal (~1 MB).
- **Verdict:** Viable but FastAPI's extra features directly serve FR-09 and provide development ergonomics at negligible cost. FastAPI recommended over bare Starlette.

### Commercial Webhook Platforms (Svix, Hook0, Hookdeck, HookBytes)

- **Strengths:** Managed webhook ingestion, retries, dead-letter queues, monitoring dashboards.
- **Weaknesses:** Violates NFR-07 (no external runtime dependencies). Adds operational cost, latency, and dependency on third-party uptime. The feature's requirements (webhook receiving + agent execution) are simple enough that a webhook platform adds unnecessary complexity.
- **Verdict:** Not recommended. The webhook processing needs are modest (one source, one destination, no fan-out).

## Recommendation

**Direction:** Hybrid — adopt FastAPI + Uvicorn for the HTTP layer and SQLite for session persistence; build the webhook-to-pipeline bridge reusing the existing engine code.

**Rationale:**
- FastAPI/Uvicorn provides the async HTTP server, health-check endpoint (FR-06), graceful shutdown via lifespan events (FR-07), structured logging hooks (FR-08), and a foundation for the admin REST API (FR-09). It meets NFR-03 (5s dispatch) and NFR-04 (10 concurrent repos) natively through async I/O.
- SQLite via stdlib + aiosqlite meets NFR-05 (crash recovery with Docker volume) and NFR-07 (single container, no external deps) without adding infrastructure.
- HMAC-SHA256 verification (NFR-01) is implemented with stdlib `hmac` following GitHub's own reference.
- The agent pipeline (FR-04, FR-05) reuses the existing `engine.py`/`run_rule.py` code, satisfying the constraint of identical agent behavior.
- Webhook registration (FR-03) and per-repo auth (NFR-02) are built as thin server-side features over these foundations.

**What is not adopted:**
- Bare Starlette: FastAPI's extra features (docs, validation, DI) are worthwhile.
- Flask: Synchronous model conflicts with concurrency and graceful-shutdown requirements.
- Commercial webhook platforms: Violate NFR-07 and are overkill.
- Dedicated webhook verification libraries: Stdlib `hmac` is sufficient and more transparent.

## Sources of Information

- **GitHub webhook validation docs** (`docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries`): Canonical HMAC-SHA256 verification recipe with Python example. Worth following even when building our own handler — the timing-safe comparison and raw-body-before-parse pattern are non-negotiable.
- **WebhookWhisper Python receiver guide** (`webhookwhisper.com/blog/webhook-receiver-python`): Production patterns for Flask and FastAPI webhook receivers. The FastAPI example shows raw body access, background task dispatch, and idempotency key tracking — all directly applicable.
- **HookRay HMAC guide** (`hookray.com/blog/webhook-signature-verification-2026`): Documents the 6 most common HMAC bugs across providers. Worth reading during implementation to avoid known pitfalls.
- **OpenAI Agents SDK `SQLiteSession`** (`openai.github.io/openai-agents-python/ref/memory/sqlite_session`): Reference implementation of an SQLite-backed session store for agent conversations. The schema pattern (separate sessions and messages tables with JSON blob storage) is a useful model even if we build our own.
- **Existing `engine.py` patterns**: The `load_flows`/`matches`/`split_steps`/`resolve_execution_for_flow` pipeline is the template for how the server dispatches webhook events. The per-repository session key (based on `owner/repo` and issue/PR ID) maps naturally onto SQLite session rows.
- **Existing `run_rule.py` patterns**: The `_run_agent` function that shells out to `opencode` and reads `$OUTCOME_YAML` is the bridge code. The server must replicate the environment setup (`GITHUB_EVENT_NAME`, `GITHUB_EVENT_PATH`, `GITHUB_TOKEN`) that the existing pipeline expects.

## Open Questions

1. Should the server use `aiosqlite` for non-blocking SQLite access, or wrap `sqlite3` calls in `run_in_executor`? `aiosqlite` is cleaner but adds a dependency; `run_in_executor` keeps zero deps. The choice affects code style in the session store layer.
2. How should the server handle `opencode` binary discovery in the Docker image? Install via the same `curl | bash` method as the workflow, or bundle a pinned version in the image? The answer affects Docker build time and upgrade strategy.
3. The existing `run_rule.py` uses `$GITHUB_OUTPUT` and temp files for inter-step communication. In the server context, should these be replaced with in-process data structures to avoid filesystem I/O, or kept as-is for consistency with the existing code path?
