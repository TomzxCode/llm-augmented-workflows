---
issue: "#16"
title: "Client/Server architecture"
status: in-review
---

# Codebase Analysis: Client/Server architecture

## Overview

The existing engine is a stateless CLI designed to run inside GitHub Actions runners. It reads event context from environment variables (`GITHUB_EVENT_NAME`, `GITHUB_EVENT_PATH`), loads flow configuration from a YAML file, matches rules against the event, and executes a pipeline of deterministic steps (`gh` CLI), an agent step (`opencode` CLI), and outcome actions (`gh` CLI). There is no HTTP server, no webhook receiver, no persistent session state, and no database.

This feature introduces an HTTP server that receives GitHub webhook payloads, wraps them into the same context the existing pipeline expects, and dispatches them through the existing engine code. The core engine (`engine.py`) is well-isolated and reusable as-is. The environment-coupling in `route.py` and `run_rule.py` must be refactored to accept data programmatically instead of from env vars. The `gh`-based step execution (`run_steps.py`, `apply_outcome.py`) requires extending for retry logic and parameter injection to eliminate env var races under concurrent multi-repo execution. The GitHub Actions workflow (`dispatch.yml`) is kept as-is for repos that remain on the workflow model — it is not replaced, it becomes one of two deployment options.

## Scope of Analysis

**Examined areas:** The entire `src/llm_augmented_workflows/` package and the `.github/workflows/dispatch.yml` workflow.

**Search entry points:**
- `src/llm_augmented_workflows/*.py` — all 7 source files read in full
- `.github/workflows/dispatch.yml` — the reusable workflow that orchestrates the CLI
- `pyproject.toml` — dependency list
- `.github/llmaw/flows.yml` — the flow configuration consumed by the engine

**Explicitly out of scope:**
- The consumer-facing wrapper workflows (`.github/wrappers/dispatch.yml`, `.github/wrappers/setup-labels.yml`)
- The shell scripts under `.github/llmaw/scripts/` (commit-sdlc.sh, ensure-branch.sh) — these are git operations unrelated to the agent pipeline
- Tests (`tests/`) — test structure is out of scope, though the existing tests demonstrate component boundaries

## Relevant Existing Components

| Component | Path | Responsibility | Interaction |
|---|---|---|---|
| `engine.py` | `src/llm_augmented_workflows/engine.py` | Pure functions: load flows, flatten rules, match events, normalize steps, compute label diffs. No I/O or environment coupling. | Reuse as-is |
| `route.py` | `src/llm_augmented_workflows/route.py` | Read event from env vars, call engine matchers, write matched rules to `$GITHUB_OUTPUT` and `MATCHED_FILE` | Extend — keep the CLI entry point; add a callable function that accepts event data directly |
| `run_rule.py` | `src/llm_augmented_workflows/run_rule.py` | Pipeline driver: orchestrate pre->agent->post->on_outcome execution, continuous chaining loop. Reads matched rules from env/files. | Refactor — extract the orchestration logic into parameterized functions; keep the CLI entry point as a thin wrapper |
| `run_steps.py` | `src/llm_augmented_workflows/run_steps.py` | Execute `labels` and `shell` steps via `gh` CLI subprocess. Reads issue/PR context from env vars (`ISSUE_NUMBER`, `PR_NUMBER`, `GH_TOKEN`). | Refactor — add retry logic with exponential backoff to `_gh()` for NFR-06; refactor `_current_subject()` and `_gh()` to accept optional parameters with env var fallback to resolve env var racing |
| `apply_outcome.py` | `src/llm_augmented_workflows/apply_outcome.py` | Read `$OUTCOME_YAML`, map verdict to labels/close/comment actions via `gh` CLI. | Refactor — inherit retry from `run_steps._gh()`; refactor `apply()` to accept optional subject context for env var isolation |
| `cli.py` | `src/llm_augmented_workflows/cli.py` | CLI entry point dispatching subcommands (`route`, `run-rule`, `run-steps`, `apply-outcome`, `sync-labels`). | Reuse as-is — server bypasses CLI but CLI stays for backward compat |
| `sync_labels.py` | `src/llm_augmented_workflows/sync_labels.py` | Create/update GitHub labels from `flows.yml` via `gh` CLI. | Reuse as-is — unrelated to pipeline execution |
| `dispatch.yml` | `.github/workflows/dispatch.yml` | GitHub Actions reusable workflow that orchestrates the CLI pipeline. | Keep as-is — not modified. Server-managed repos bypass it; workflow-model repos continue using it unchanged |
| `pyproject.toml` | `pyproject.toml` | Package config; single runtime dependency (pyyaml). | Extend — add `fastapi`, `uvicorn`, `aiosqlite`, `httpx` |

## Dependency and Coupling Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        SERVER (new)                                      │
│  FastAPI routes ──> webhook handler ──> HMAC verify ──> session store    │
│                          │                     │                          │
│                          ▼                     ▼                          │
│                   route refactor     SQLite (aiosqlite)                   │
│                          │                                                │
│                          ▼                                                │
│                   run_rule refactor                                       │
│                     │        │                                             │
│                     ▼        ▼                                             │
│               run_steps.py  apply_outcome.py                               │
│               (gh CLI)      (gh CLI → GitHub API)                         │
│                     │                                                      │
│                     └── subprocess (gh, opencode, bash) ───> Docker env   │
└─────────────────────────────────────────────────────────────────────────┘

Coupling notes:

1. ENVIRONMENT VARIABLES — route.py and run_rule.py read GITHUB_EVENT_NAME,
   GITHUB_EVENT_PATH, MATCHED_FILE, MATCHED_RULE, OUTCOME_YAML, EXECUTION,
   FLOWS_FILE, MODEL, AGENTS_REPOSITORY from os.environ. Every one of these
   must be available when the pipeline runs, whether in GitHub Actions or in
   the server. This is the primary coupling to the Actions environment.

2. gh CLI — Every GitHub API mutation goes through the `gh` CLI subprocess.
   run_steps.py, apply_outcome.py, and sync_labels.py all invoke `gh` with
   GH_TOKEN set. The `gh` binary must be installed in the Docker image.
   Coupling: tight (the code cannot mutate GitHub without `gh`).

3. opencode CLI — run_rule.py._run_agent() shells out to `opencode run ...`.
   The `opencode` binary must be installed in the Docker image and the
   agent's skill/prompt files must be available.

4. SQLite — new dependency introduced by the server for session persistence.
   The existing engine has no database. The server's session store is the
   first persistent store and has no coupling to existing code.

5. DOCKER IMAGE — The server container must include: the engine package,
   FastAPI/Uvicorn runtime, `gh` CLI, `opencode` CLI, `bash`, `git`.
   The existing engine has no Docker image; the server creates one.

Blast radius of changes:
- Modifying engine.py would affect all consumers (CLI and server). Keep it pure.
- Modifying run_rule.py's orchestration logic affects both execution paths.
  Refactor to accept callable dependencies so the server can provide its own
  context without changing the orchestration.
- Modifying run_steps.py or apply_outcome.py affects both execution paths.
  Keep backward-compatible signatures (env var fallbacks) so the CLI path
  remains unchanged while the server path passes context directly.
```

## Changeability Assessment

### engine.py

- **Current state:** 449 lines of pure functions (no I/O, no subprocess, no env vars). Tested by 510 lines of unit tests. Data models (`When`, `AgentStep`, `Rule`) are frozen dataclasses used across the codebase.
- **Change disposition:** Reuse as-is
- **Rationale:** The module is already well-isolated by design (see its docstring: "intentionally free of GitHub/HTTP side effects"). Every function the server needs — `load_flows`, `flatten_rules`, `matches`, `resolve_dispatch_execution`, `find_next_rules` — is called without modification. The server passes webhook-derived event data into `matches()` the same way route.py does.
- **Risk:** Low — no changes needed
- **Constraints:** The function signatures must not change (or must be extended backward-compatibly). The frozen dataclass contracts must remain stable.

### route.py

- **Current state:** 96 lines. Calls `engine.load_flows`, `engine.flatten_rules`, `engine.matches`, then writes results to `$GITHUB_OUTPUT` env file and optionally a `MATCHED_FILE`. All inputs come from env vars.
- **Change disposition:** Extend
- **Rationale:** The CLI entry point (`main()`) must continue working for workflow-model repos. The server needs the same logic but with data passed programmatically instead of via env vars. Add a new function (e.g., `match_event(event_name, payload, flows_path, ...)`) that encapsulates the pure matching logic and returns the matched rules. The existing `main()` calls this new function after reading env vars. The server calls it directly.
- **Risk:** Low — the new function is a pure extraction; no behavior change
- **Constraints:** The `_write_output` and `_load_payload` helpers are implementation details of the CLI path and should not be exposed to the server. The matched-rules output format (the matrix dict shape from `rule_to_matrix`) must remain stable — it is consumed by `run_rule.py`. **Behavioral identity:** the refactored function must produce identical rule matches and matrix entries as the current `main()` for the same event — downstream users must see the same agent comments, labels, and outcomes regardless of execution path (CLI vs server).

### run_rule.py

- **Current state:** 169 lines. Pipeline driver: reads matched rules from `MATCHED_FILE` or `MATCHED_RULE` env, resolves execution mode, then runs each rule through `_execute_rule()`. Continuous mode chains rules by fetching labels and calling `engine.find_next_rules()`. All I/O goes through env vars, `run_steps`, `apply_outcome`, and subprocess calls.
- **Change disposition:** Refactor
- **Rationale:** The orchestration logic (`_execute_rule` pipeline, `_run_continuous` loop) is the core of the server's agent execution path. But `_read_rules()`, `_resolve_execution()`, `_load_all_rules()`, and `_fetch_labels()` all read from env vars. The server must provide this data directly. Extract the orchestration into a function or class that accepts dependencies (matched rules, flows data, label provider, outcome path) as parameters. The existing `main()` becomes a thin wrapper that reads env vars and calls the extracted function.
- **Risk:** Medium — the continuous mode loop is non-trivial. A mistake in the extraction could break the chaining logic. Mitigation: the refactored code must be covered by the existing tests (and new tests should cover the extracted function directly).
- **Constraints:** The agent invocation via `opencode run` subprocess must continue to work. The `OUTCOME_YAML` env var convention must be preserved (or replaced by a parameter that defaults to the env var). The `gh` subprocess calls in `run_steps` and `apply_outcome` must inherit `GH_TOKEN` from the process environment. **Behavioral identity:** the refactored pipeline must produce identical outcomes (same labels, comments, closes, PR actions) as the current `main()` for the same input event — server users must not see behavioral differences from workflow users.

### run_steps.py

- **Current state:** 117 lines. Functions: `_gh()`, `_current_subject()`, `_current_labels()`, `_find_linked_issue()`, `apply_labels()`, `run_shell()`, `main()`. All GitHub mutations go through `gh` CLI. Reads `ISSUE_NUMBER`, `PR_NUMBER`, `GH_TOKEN` from env.
- **Change disposition:** Refactor
- **Rationale:** Two changes needed. (1) **Retry with exponential backoff (NFR-06):** `_gh()` calls `subprocess.run` with `check=True` and no retry. In GitHub Actions, transient network errors sometimes auto-retry at the runner level; in the server, no such implicit retry exists. Add exponential backoff (max 3 retries, starting delay 1s, multiplier 2) around `subprocess.run` in `_gh()`, catching `subprocess.CalledProcessError`. (2) **Parameter injection for env var isolation:** `_current_subject()` and `_gh()` must accept optional parameters. The server passes `GH_TOKEN`, `ISSUE_NUMBER`, `PR_NUMBER` directly instead of writing env vars that would race across concurrent requests. The env var fallback preserves backward compatibility for the CLI/Workflow path.
- **Risk:** Medium — retry logic must not mask genuine (non-transient) failures. Parameter injection must not change behavior when env vars are the only source. Mitigation: retry only on `CalledProcessError` (non-zero exit), not on other exceptions. Parameter injection defaults to `os.environ.get()` when the parameter is `None`, making the refactored code behavior-identical to the current code when called from the CLI path.
- **Constraints:** `gh` CLI must be installed in the Docker image. Retry delays (1s, 2s, 4s) must not exceed NFR-03 (5s dispatch budget) — retries apply to individual API calls, not to the full dispatch. The `gh` subprocess output format expectations (`capture=True` for JSON parsing in `_current_labels`, `_find_linked_issue`) must be preserved.

### apply_outcome.py

- **Current state:** 108 lines. Reads `$OUTCOME_YAML` path from env, parses YAML, maps verdict to labels/close/comment via `gh` CLI.
- **Change disposition:** Refactor
- **Rationale:** (1) **Inherits retry from `_gh()`:** no separate retry logic needed — `_post_comment()` and `_close()` delegate to `run_steps._gh()`, which gains retry. (2) **Parameter injection for env var isolation:** `apply()` must accept optional `number`, `kind` parameters. The `run_steps.apply_labels()` and `run_steps._current_subject()` calls within `apply()` must also use the server-provided context instead of reading env vars that could race. Backward-compatible env var fallback preserves the CLI path.
- **Risk:** Low — retry is inherited from `_gh()`. Parameter injection follows the same pattern as `run_steps.py`.
- **Constraints:** The `OUTCOME_YAML` env var path convention must be preserved (or accept a path parameter). `GH_TOKEN` for the `gh` calls is passed through the refactored `_gh()`.

### cli.py

- **Current state:** 47 lines. Entry point dispatching to subcommand modules.
- **Change disposition:** Reuse as-is
- **Rationale:** The server does not use the CLI — it imports the Python modules directly. The CLI must remain for repos that continue using the GitHub Actions workflow model. No changes needed.
- **Risk:** None
- **Constraints:** None

### sync_labels.py

- **Current state:** 50 lines. Uses `gh` CLI for label CRUD.
- **Change disposition:** Reuse as-is
- **Rationale:** Unrelated to the pipeline. Could be run from the server admin API or from the CLI.
- **Risk:** None
- **Constraints:** Needs `gh` in Docker image if called from the server.

### dispatch.yml (GitHub Actions workflow)

- **Current state:** 177 lines. Reusable workflow that: creates an App token, checks out consumer and engine repos, installs opencode, clones skills repositories, runs `route` + `run-rule` steps.
- **Change disposition:** Keep as-is
- **Rationale:** This workflow is not modified. Repos that adopt the server no longer need this workflow — the server replaces the entire orchestration. Repos that do not migrate continue using it unchanged. The analysis does not propose any changes to `dispatch.yml`.
- **Risk:** None — not modified. The workflow and server are independent deployment options with no shared state.
- **Constraints:** The workflow must remain functional for non-migrated repos. No shared state or configuration between the workflow path and the server path.

### New: Server package (greenfield)

- **Disposition:** Create new
- **Components to build:**
  - Webhook receiver (FastAPI route, HMAC-SHA256 verification)
  - Session store (SQLite via aiosqlite, per-repo session data)
  - Registration store (webhook targets, secrets, per-repo tokens)
  - Webhook-to-pipeline bridge (construct event context, call route/run-rule functions)
  - Admin REST API (optional, FR-09)
  - Dockerfile (engine + server + gh + opencode + bash)
  - Health check endpoint (GET /health, FR-06)
  - **Graceful shutdown (FR-07):** Uvicorn lifespan handler catches SIGTERM, sets a "shutting down" flag, drains in-flight agent executions (waits for `subprocess.run` in `_run_agent` and `_gh` calls to complete), rejects new webhook requests with HTTP 503 during drain, and exits after a configurable drain timeout (default 30s). In-flight tracking uses a set of active `asyncio.Task` objects or a thread-safe counter.
  - **Structured logging (FR-08):** Server-side logging uses `structlog` (or stdlib `logging` with JSON formatter) to emit structured events for webhook receipt, HMAC verification result, rule match outcomes, agent execution start/end/duration, `gh` API calls, retry attempts, and errors. The existing CLI path keeps its plain-text `logging.basicConfig` format (unchanged). The server path adds a structured handler keyed on a `service=llmaw-server` context variable.
- **Integration boundary:** The server calls the refactored `route.py` and `run_rule.py` functions. It passes `GH_TOKEN`, `ISSUE_NUMBER`, `PR_NUMBER` as parameters to `run_steps.py` and `apply_outcome.py` functions instead of setting env vars, eliminating the race condition under concurrent multi-repo execution. It sets env vars only for subprocess commands (`opencode run`, `bash`) that inherit them naturally.

## Migration and Impact Considerations

### For run_rule.py refactoring:

1. **Extract `execute_rules` function.** Accept `matched_rules: list[dict]`, `flows_path: str`, `model: str`, `agents_repository: str`, `execution: str`, `max_iterations: int`, `outcome_path: str | None` as parameters instead of reading from env. Return exit code.

2. **Backward compatibility.** `main()` reads env vars and calls the extracted function. The `_read_rules()`, `_resolve_execution()`, `_load_all_rules()` helpers collapse into the function body or its callers.

3. **De-risking.** No feature flag needed — the server path is entirely new code that calls the refactored functions. The CLI path still enters through `main()` and is unchanged. Test both paths in CI.

### For route.py extending:

1. **Extract `match_event(event_name, payload, flows_path, model, agents_repo, ...)` function.** Returns the list of matched `Rule` objects or matrix dicts. The existing `main()` calls this after reading env vars.

2. **Output format stability.** The `rule_to_matrix` dict shape must not change — it is consumed by `run_rule.py`. If new fields are needed, add them as optional to avoid breaking the CLI path.

3. **Backward compatibility.** `_write_output` and `GITHUB_OUTPUT` writing remain in `main()` only. The server gets results as return values.

### For run_steps.py refactoring (retry + parameter injection):

1. **Add `_gh_with_retry(args, token=None, capture=False)`.** Wraps the current `subprocess.run` with exponential backoff (3 attempts, delays 1s/2s/4s). Only retries on `subprocess.CalledProcessError`. Accepts optional `token` parameter — when provided, sets `GH_TOKEN` in the subprocess env instead of relying on the parent process env. Falls back to `os.environ.get("GH_TOKEN")` when `token` is `None`.

2. **Refactor `_current_subject(number=None, kind=None)`.** When `number` and `kind` are provided, return them directly. Otherwise fall back to `os.environ.get("ISSUE_NUMBER")` / `os.environ.get("PR_NUMBER")`.

3. **Refactor `_current_labels(number, kind, token=None)`.** Pass `token` through to `_gh_with_retry`.

4. **Refactor `apply_labels(step, number=None, kind=None, token=None)`.** Pass subject context and token through.

5. **Refactor `_find_linked_issue(pr_title=None, pr_body=None)`.** Accept optional PR metadata; fall back to env vars.

6. **Migrate `_gh` callers to `_gh_with_retry`.** The `_gh` function stays for backward compatibility but its callers switch to the retry-enabled version.

### For apply_outcome.py refactoring (parameter injection):

1. **Refactor `apply(on_outcome, rule_id, number=None, kind=None, token=None)`.** Accept optional subject context; pass it to `run_steps.apply_labels()` and `run_steps._current_subject()`.

### For the server Docker image:

1. **gh CLI.** Install via the official GitHub CLI installation script (`apt-get` or the install script). Version: latest stable.

2. **opencode CLI.** Install via `curl -fsSL https://opencode.ai/install | bash` (same method as the GitHub Actions workflow). Consider pinning a version in the Dockerfile for reproducible builds.

3. **Engine code.** The engine package is included in the Docker image at build time (as part of the project). No runtime checkout needed — this is a key improvement over the workflow model.

4. **Agent skills/prompts.** The `AGENTS_REPOSITORY` must be cloned or mounted into the container, or fetched on first use. Same as the workflow model.

### For session persistence (SQLite):

1. **Schema design.** Minimal: `repositories` table (owner, repo, secret_token, gh_token), `sessions` table (repo_id, subject_type, subject_id, conversation_history JSON, created_at, updated_at). The conversation history is loaded before agent execution and persisted after.

2. **Crash recovery.** Committed session state survives via Docker volume (NFR-05). In-flight agent steps are lost on crash (acceptable per NFR-05 spec). SQLite WAL mode allows concurrent reads during writes.

3. **Rollout.** New schema — no migration from existing data (there is none).

### For retry logic (NFR-06 / FR-05):

1. **Where retry applies.** Every `gh` CLI call in `run_steps.py` (`issue view`, `issue edit`, `pr view`, `pr edit`, `issue comment`, `pr comment`, `issue close`, `pr close`). The `on_outcome` actions in `apply_outcome.py` decompose to these same `gh` calls.

2. **Retry strategy.** 3 attempts, exponential backoff (1s, 2s, 4s). Retry only on `subprocess.CalledProcessError` (non-zero exit from `gh`). Immediate re-raise on other exceptions (e.g., `FileNotFoundError` — `gh` not installed).

3. **What happens when all retries are exhausted.** Log the failure at ERROR level with the attempted command, exit code, stderr, and retry count. The pipeline continues to the next step — a single failed `gh` call does not abort the entire rule execution. This is consistent with the current behavior where a non-zero exit from `gh` in `run_steps.main()` propagates as an unhandled exception and fails the step.

### For graceful shutdown (FR-07):

1. **Signal handling.** Uvicorn's lifespan handler catches SIGTERM. An `asyncio.Event` (`shutdown_event`) is set.

2. **In-flight tracking.** An `asyncio.TaskGroup` or set of active tasks tracks in-flight agent executions. The webhook handler registers each dispatched pipeline invocation.

3. **Drain behavior.** When shutdown is requested: (a) set server health to unhealthy (health endpoint returns 503), (b) reject new webhook requests with 503, (c) await completion of registered in-flight tasks (max drain timeout 30s), (d) tasks that exceed the timeout are cancelled and logged, (e) exit.

4. **At-most-once semantics.** In-flight tasks that are cancelled during drain lose their outcome (same as a crash). Committed session state from prior iterations survives.

### For structured logging (FR-08):

1. **Server-side logger.** Use `structlog` (recommended by existing solutions survey) or a stdlib `logging` JSON formatter. Log events: webhook receipt, HMAC verification result (pass/fail), rule match results (matched rule IDs), agent execution (start, duration, exit code), `gh` API calls (command, duration, retry count), outcome application, errors with stack traces.

2. **Existing CLI path.** Unchanged — continues using `logging.basicConfig` with plain-text format. The server path and CLI path are separate runtime contexts; they never share a logger.

### For env var isolation (concurrent multi-repo):

1. **Problem.** `run_steps._current_subject()` reads `ISSUE_NUMBER` / `PR_NUMBER` from `os.environ`. `_gh()` reads `GH_TOKEN` from `os.environ`. If two webhook requests for different repos arrive concurrently and share a thread pool, one request's env var writes could race with another's reads.

2. **Solution: parameter injection with env var fallback.** Refactor `_current_subject(number, kind)`, `_gh(args, token)`, `apply_labels(step, number, kind, token)`, and `apply(outcome, rule_id, number, kind, token)` to accept optional parameters. When parameters are provided (server path), env vars are not read. When parameters are `None` (CLI path), env vars are read as today.

3. **Thread safety.** The server dispatches each pipeline invocation via `run_in_executor` to a thread pool. Since the server passes all context as function parameters, the thread workers share no mutable state. The `os.environ` dict is never written by the server path.

## Assumptions About Existing Code

- The `gh` CLI commands used by `run_steps.py` and `apply_outcome.py` return the same exit codes and output formats in a Docker container as in GitHub Actions. Verified by reading the code: they use `subprocess.run` with `check=True` and parse JSON output from `gh` subcommands.
- The `opencode run` command works identically when invoked from a Docker container as from a GitHub Actions runner. The opencode CLI's `--dangerously-skip-permissions` flag controls its own permission checks, so the container boundary should not add friction.
- The `matches()` function in `engine.py` covers all event types the server will receive (push, pull_request, issue_comment, issues per FR-01). Verified by reading the function: it handles event type, action, label, merged, branch_prefix, and body_contains checks against the payload. True for the stated event types.
- The existing engine's `find_next_rules()` function for continuous chaining only matches rules with `issues` event type and `labeled` action. This means continuous mode is specific to issue label workflows and PR/comment rules are never auto-chained. Verified by reading the function.
- The `subprocess.CalledProcessError` exception from `gh` CLI calls is sufficient to detect transient failures (rate limits, network blips, temporary GitHub API errors) versus permanent ones (bad credentials, missing resource). If `gh` exits non-zero for both transient and permanent failures with no distinguishable exit code, the retry logic may retry permanent failures unnecessarily but will still exhaust its budget and fail fast.

## Open Questions

1. ~~Should the server use `os.environ` passthrough for `GH_TOKEN` and other env vars when calling into `run_steps.py` and `apply_outcome.py`, or should those functions be refactored to accept tokens as parameters?~~ **Resolved.** Use parameter injection with env var fallback (described above). The server passes all context as function parameters. The CLI path continues using env vars. This eliminates the race condition without changing behavior for existing consumers.

2. ~~The `_current_subject()` function in `run_steps.py` reads `ISSUE_NUMBER` and `PR_NUMBER` from env. In the server, this context is derived from the webhook payload. Should the server set these env vars before calling pipeline code, or should the refactored pipeline accept the subject as a parameter?~~ **Resolved.** Use parameter injection (same resolution as Q1). The server passes the subject as a parameter; env vars are not written.

3. The `_run_agent` function in `run_rule.py` shells out to `opencode run` and reads the agent's ref file from disk. In the server, the skill/prompt files must be available inside the container at the expected path. How should skill files be distributed in the server model — cloned at container start, mounted as a volume, or fetched on first use? This affects startup time and Docker image size.

4. The existing `route.py` reads `FORCE_RULE_ID` from env for manual workflow dispatch. Does the server need a similar force-rule bypass (e.g., for admin API testing), or is this only relevant to the GitHub Actions path?
