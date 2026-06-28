---
issue: "#16"
title: "Client/Server architecture"
status: in-review
---

# Codebase Analysis: Client/Server architecture

## Overview

The existing engine is a stateless CLI designed to run inside GitHub Actions runners. It reads event context from environment variables (`GITHUB_EVENT_NAME`, `GITHUB_EVENT_PATH`), loads flow configuration from a YAML file, matches rules against the event, and executes a pipeline of deterministic steps (`gh` CLI), an agent step (`opencode` CLI), and outcome actions (`gh` CLI). There is no HTTP server, no webhook receiver, no persistent session state, and no database.

This feature introduces an HTTP server that receives GitHub webhook payloads, wraps them into the same context the existing pipeline expects, and dispatches them through the existing engine code. The core engine (`engine.py`) is well-isolated and reusable as-is. The environment-coupling in `route.py` and `run_rule.py` must be refactored to accept data programmatically instead of from env vars. The `gh`-based step execution (`run_steps.py`, `apply_outcome.py`) is reusable provided `gh` is installed in the Docker image. The GitHub Actions workflow (`dispatch.yml`) is not needed for server-managed repos but must remain for repos that keep the workflow model.

## Scope of Analysis

**Examined areas:** The entire `src/llm_augmented_workflows/` package and the `.github/workflows/dispatch.yml` workflow.

**Search entry points:**
- `src/llm_augmented_workflows/*.py` — all 7 source files read in full
- `.github/workflows/dispatch.yml` — the reusable workflow that orchestrates the CLI
- `pyproject.toml` — dependency list
- `.github/llmaw/flows.yml` — the flow configuration consumed by the engine

**Explicitly out of scope:**
- The consumer-facing wrapper workflows (`.github/workflows/dispatch.yml` consumer usage patterns)
- The shell scripts under `.github/llmaw/scripts/` (commit-sdlc.sh, ensure-branch.sh) — these are git operations unrelated to the agent pipeline
- Tests (`tests/`) — test structure is out of scope, though the existing tests demonstrate component boundaries

## Relevant Existing Components

| Component | Path | Responsibility | Interaction |
|---|---|---|---|
| `engine.py` | `src/llm_augmented_workflows/engine.py` | Pure functions: load flows, flatten rules, match events, normalize steps, compute label diffs. No I/O or environment coupling. | Reuse as-is |
| `route.py` | `src/llm_augmented_workflows/route.py` | Read event from env vars, call engine matchers, write matched rules to `$GITHUB_OUTPUT` and `MATCHED_FILE` | Extend — keep the CLI entry point; add a callable function that accepts event data directly |
| `run_rule.py` | `src/llm_augmented_workflows/run_rule.py` | Pipeline driver: orchestrate pre->agent->post->on_outcome execution, continuous chaining loop. Reads matched rules from env/files. | Refactor — extract the orchestration logic into parameterized functions; keep the CLI entry point as a thin wrapper |
| `run_steps.py` | `src/llm_augmented_workflows/run_steps.py` | Execute `labels` and `shell` steps via `gh` CLI subprocess. Reads issue/PR context from env vars (`ISSUE_NUMBER`, `PR_NUMBER`, `GH_TOKEN`). | Reuse as-is — works in any environment with `gh` installed |
| `apply_outcome.py` | `src/llm_augmented_workflows/apply_outcome.py` | Read `$OUTCOME_YAML`, map verdict to labels/close/comment actions via `gh` CLI. | Reuse as-is — works in any environment with `gh` installed |
| `cli.py` | `src/llm_augmented_workflows/cli.py` | CLI entry point dispatching subcommands (`route`, `run-rule`, `run-steps`, `apply-outcome`, `sync-labels`). | Reuse as-is — server bypasses CLI but CLI stays for backward compat |
| `sync_labels.py` | `src/llm_augmented_workflows/sync_labels.py` | Create/update GitHub labels from `flows.yml` via `gh` CLI. | Reuse as-is — unrelated to pipeline execution |
| `dispatch.yml` | `.github/workflows/dispatch.yml` | GitHub Actions reusable workflow that orchestrates the CLI pipeline. | Replace — for server-managed repos the workflow is superseded; keep for workflow-model repos |
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
  Keep their signatures stable; they are the "leaf" modules.
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
- **Rationale:** The CLI entry point (`main()`) must continue working for workflow-model repos. The server needs the same logic but with data passed programmatically instead of via env vars. Add a new function (e.g., `route_event(event_name, payload, flows_path, ...)` or `match_rules(...)`) that encapsulates the pure matching logic and returns the matched rules. The existing `main()` calls this new function after reading env vars. The server calls it directly.
- **Risk:** Low — the new function is a pure extraction; no behavior change
- **Constraints:** The `_write_output` and `_load_payload` helpers are implementation details of the CLI path and should not be exposed to the server. The matched-rules output format (the matrix dict shape from `rule_to_matrix`) must remain stable — it is consumed by `run_rule.py`.

### run_rule.py

- **Current state:** 169 lines. Pipeline driver: reads matched rules from `MATCHED_FILE` or `MATCHED_RULE` env, resolves execution mode, then runs each rule through `_execute_rule()`. Continuous mode chains rules by fetching labels and calling `engine.find_next_rules()`. All I/O goes through env vars, `run_steps`, `apply_outcome`, and subprocess calls.
- **Change disposition:** Refactor
- **Rationale:** The orchestration logic (`_execute_rule` pipeline, `_run_continuous` loop) is the core of the server's agent execution path. But `_read_rules()`, `_resolve_execution()`, `_load_all_rules()`, and `_fetch_labels()` all read from env vars. The server must provide this data directly. Extract the orchestration into a function or class that accepts dependencies (matched rules, flows data, label provider, outcome path) as parameters. The existing `main()` becomes a thin wrapper that reads env vars and calls the extracted function.
- **Risk:** Medium — the continuous mode loop is non-trivial. A mistake in the extraction could break the chaining logic. Mitigation: the refactored code must be covered by the existing tests (and new tests should cover the extracted function directly).
- **Constraints:** The agent invocation via `opencode run` subprocess must continue to work. The `OUTCOME_YAML` env var convention must be preserved (or replaced by a parameter that defaults to the env var). The `gh` subprocess calls in `run_steps` and `apply_outcome` must inherit `GH_TOKEN` from the process environment.

### run_steps.py

- **Current state:** 117 lines. Functions: `_gh()`, `_current_subject()`, `_current_labels()`, `_find_linked_issue()`, `apply_labels()`, `run_shell()`, `main()`. All GitHub mutations go through `gh` CLI. Reads `ISSUE_NUMBER`, `PR_NUMBER`, `GH_TOKEN` from env.
- **Change disposition:** Reuse as-is
- **Rationale:** These functions work identically in a Docker container as long as `gh` is installed and `GH_TOKEN` is set. The env var reads (`ISSUE_NUMBER`, `PR_NUMBER`) are set by the server before calling pipeline code. No code changes needed.
- **Risk:** Low — `gh` must be installed in the Docker image. The server must set `GH_TOKEN` per-repository before each pipeline invocation.
- **Constraints:** `gh` CLI version must be compatible with the GitHub API endpoints used. The `GH_TOKEN` must be a valid GitHub App installation token or PAT with appropriate scope.

### apply_outcome.py

- **Current state:** 108 lines. Reads `$OUTCOME_YAML` path from env, parses YAML, maps verdict to labels/close/comment via `gh` CLI.
- **Change disposition:** Reuse as-is
- **Rationale:** Same as run_steps — the `gh` subprocess approach works in any environment. The `OUTCOME_YAML` env var is set by the server before calling pipeline code.
- **Risk:** Low — same considerations as run_steps
- **Constraints:** Same as run_steps — `gh` in Docker image, `GH_TOKEN` set by server.

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
- **Change disposition:** Replace
- **Rationale:** Repos that adopt the server no longer need this workflow. The server replaces the entire orchestration: webhook receipt, event matching, agent execution, action dispatch. The workflow stays for repos that do not migrate to the server model. It is not modified — it simply becomes one of two deployment options.
- **Risk:** Low — not modified. Only the server delivery model is new.
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
  - Health check endpoint (FR-06)
- **Integration boundary:** The server calls the refactored `route.py` and `run_rule.py` functions. It sets the env vars that `run_steps.py` and `apply_outcome.py` expect before calling into the pipeline.

## Migration and Impact Considerations

### For run_rule.py refactoring:

1. **Extract `execute_rule` parameters.** Currently `_execute_rule` reads matched rule data from the dict passed in (already parameterized). But `_run_agent` reads `agent["model"]`, `agent["kind"]`, `agent["ref"]` directly and shells out. No change needed for the server — it passes the same dict shape.

2. **Extract `_run_continuous` parameters.** Currently reads `FLOWS_FILE`, `MODEL`, `AGENTS_REPOSITORY`, `LLMAW_MAX_ITERATIONS` from env, and calls `_load_all_rules()` which reads flows from disk. The refactored version should accept these as parameters.

3. **Backward compatibility.** The `main()` function stays unchanged. The server path calls the new parameterized functions. Both paths share the same underlying logic.

4. **De-risking.** No feature flag needed — the server path is entirely new code that calls the refactored functions. The CLI path still enters through `main()` and is unchanged. Test both paths in CI.

### For route.py extending:

1. **Extract `match_event(event_name, payload, flows_path, ...)` function.** Returns the list of matched `Rule` objects or matrix dicts. The existing `main()` calls this after reading env vars.

2. **Output format stability.** The `rule_to_matrix` dict shape must not change — it is consumed by `run_rule.py`. If new fields are needed, add them as optional to avoid breaking the CLI path.

3. **Backward compatibility.** The `_write_output` function and `GITHUB_OUTPUT` writing remain in `main()` only. The server gets results as return values.

### For the server Docker image:

1. **gh CLI.** Install via the official GitHub CLI installation script (`apt-get` or the install script). Version: latest stable.

2. **opencode CLI.** Install via `curl -fsSL https://opencode.ai/install | bash` (same method as the GitHub Actions workflow). Consider pinning a version in the Dockerfile for reproducible builds.

3. **Engine code.** The engine package is included in the Docker image at build time (as part of the project). No runtime checkout needed — this is a key improvement over the workflow model.

4. **Agent skills/prompts.** The `AGENTS_REPOSITORY` must be cloned or mounted into the container, or fetched on first use. Same as the workflow model.

### For session persistence (SQLite):

1. **Schema design.** Minimal: `repositories` table (owner, repo, secret_token, gh_token), `sessions` table (repo_id, subject_type, subject_id, conversation_history JSON, created_at, updated_at). The conversation history is loaded before agent execution and persisted after.

2. **Crash recovery.** Committed session state survives via Docker volume (NFR-05). In-flight agent steps are lost on crash (acceptable per NFR-05 spec). SQLite WAL mode allows concurrent reads during writes.

3. **Rollout.** New schema — no migration from existing data (there is none).

## Assumptions About Existing Code

- The `gh` CLI commands used by `run_steps.py` and `apply_outcome.py` return the same exit codes and output formats in a Docker container as in GitHub Actions. Verified by reading the code: they use `subprocess.run` with `check=True` and parse JSON output from `gh` subcommands.
- The `opencode run` command works identically when invoked from a Docker container as from a GitHub Actions runner. The opencode CLI's `--dangerously-skip-permissions` flag controls its own permission checks, so the container boundary should not add friction.
- The `matches()` function in `engine.py` covers all event types the server will receive (push, pull_request, issue_comment, issues per FR-01). Verified by reading the function: it handles event type, action, label, merged, branch_prefix, and body_contains checks against the payload. True for the stated event types.
- The existing engine's `find_next_rules()` function for continuous chaining only matches rules with `issues` event type and `labeled` action. This means continuous mode is specific to issue label workflows and PR/comment rules are never auto-chained. Verified by reading the function.

## Open Questions

1. Should the server use `os.environ` passthrough for `GH_TOKEN` and other env vars when calling into `run_steps.py` and `apply_outcome.py`, or should those functions be refactored to accept tokens as parameters? Passthrough is simpler (no code changes in leaf modules) but means the server must set env vars before each pipeline invocation — potentially problematic for concurrent multi-repo execution. If `run_in_executor` is used per-repo with thread-local env, this is manageable. If concurrent requests share threads, env vars will race.
2. The `_current_subject()` function in `run_steps.py` reads `ISSUE_NUMBER` and `PR_NUMBER` from env. In the server, this context is derived from the webhook payload. Should the server set these env vars before calling pipeline code, or should the refactored pipeline accept the subject as a parameter? Same race concern as above.
3. The `_run_agent` function in `run_rule.py` shells out to `opencode run` and reads the agent's ref file from disk. In the server, the skill/prompt files must be available inside the container at the expected path. How should skill files be distributed in the server model — cloned at container start, mounted as a volume, or fetched on first use? This affects startup time and Docker image size.
4. The existing `route.py` reads `FORCE_RULE_ID` from env for manual workflow dispatch. Does the server need a similar force-rule bypass (e.g., for admin API testing), or is this only relevant to the GitHub Actions path?
