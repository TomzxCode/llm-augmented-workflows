---
issue: "#18"
title: "Support other harness CLI"
status: approved
revision: 2
---

# Existing Solutions: Support Other Harness CLI

## Overview

Surveyed 12 candidates across internal code, open-source libraries, commercial platforms, and standards to determine how best to make the agent step configurable for any AI CLI runtime. No off-the-shelf library solves the exact combination (configurable command + verdict parser plugin + setup hook) in this project's Python tech stack. The recommendation is to **build** a lightweight abstraction using Python's `subprocess` module as the foundation, adopting proven patterns from flowai-workflow (runtime selection in YAML config), StackStorm (pluggable runner registry), and structured exit code conventions for the verdict parser contract.

## Search Scope

| Source | Searched | Notes |
|---|---|---|
| Internal codebase | Yes | `src/llm_augmented_workflows/run_rule.py`, `engine.py`, `run_steps.py` — no existing abstraction; opencode is hardcoded. The `shell` step type provides a precedent for running arbitrary commands but lacks verdict routing. |
| Open-source | Yes | flowai-workflow (MIT, Deno/TS), StackStorm (Apache 2.0, Python), Mastra (MIT, TS), n8n (Sustainable, TS), opencode-cli-enforcer (MIT, TS), verdict (MIT, Python), cli-agent-spec exit codes; Python ecosystem: pluggy (MIT, plugin framework used by pytest), sh (MIT, subprocess), invoke (BSD, subprocess/task runner), plumbum (MIT, subprocess/remote) |
| Commercial / SaaS | Yes | Temporal (MIT, Go/Python/TS), n8n Cloud, Anthropic Claude Code CLI, Codex CLI, Google Gemini CLI |
| Standards / protocols | Yes | MCP (JSON-RPC over stdio), Unix exit code conventions, cli-agent-spec ExitCode schema, Python subprocess docs |
| Reference material | Yes | Structured exit reasons blog post (JoelClaw), Safe IPC Patterns (Zylos Research), Codex App Server Protocol, Claude Agent SDK architecture |

## Candidate Solutions

| Solution | Type | License | Maturity | Covers | Gaps |
|---|---|---|---|---|---|
| Internal `shell` step | Internal | MIT (project) | Active | Arbitrary command execution via `subprocess.run` | No verdict routing, no setup hook, no env mapping, no timeout config |
| flowai-workflow | Library | MIT | Active | FR-01 (runtime selectable per node), `runtime_args`, timeout per node | Deno/TS not Python; no verdict parser abstraction; no sandboxing |
| StackStorm runners | Platform | Apache 2.0 | Mature | FR-01 (pluggable action runners via stevedore), timeout, env vars, result handling | Heavy platform dependency (RabbitMQ, MongoDB, 12 microservices); no AI-specific support |
| Mastra | Framework | MIT | Active | FR-01 (model routing across 40+ providers), FR-07 (env vars per agent) | TS not Python; full framework adoption; no verdict parser contract |
| n8n AI Agent | Platform | Sustainable | Mature | FR-01 (multi-provider LLM), output parser interface, timeout, HITL | Full platform migration; visual UI focus; no CLI customization; n8n Cloud pricing starts at $20/mo (self-hosted free) |
| opencode-cli-enforcer | Library | MIT | Active (small npm package, 0 stars, single maintainer) | FR-01 (multi-CLI orchestration), circuit breaker, retry, fallback chain | TS; no verdict parser abstraction; no setup hooks |
| Temporal | Platform | MIT | Mature | FR-01 (durable activity execution), timeout, retry, env vars | Heavy infrastructure (server + worker); overkill for single-step agent invocation; Temporal Cloud pricing per workflow-task (~$0.10 per 10k tasks) |
| cli-agent-spec ExitCode | Standard | MIT | Draft | FR-03 (structured exit codes with retryable/side-effects semantics) | Not a library; requires integration; no opinion on stdin parsing |
| pluggy | Library | MIT | Mature | FR-09 (hook-based plugin loading via hookspec/hookimpl decorators) | Not a parser framework; provides plugin discovery/loading pattern only |
| sh, invoke, plumbum | Library | MIT / BSD / MIT | Mature | FR-01 (subprocess management: command execution, timeout, env passthrough) | No verdict routing; sh is synchronous-only; invoke adds task-runner semantics; plumbum supports remote |
| verdict (haizelabs) | Library | MIT | Active | FR-03 (structured output extraction from LLM), composable judge protocols | LLM-as-judge framework, not a generic CLI verdict parser; the RegexExtractor pattern for extracting JSON fields from LLM output is informative for built-in parsers |
| Structured Exit Reasons | Reference | — | Conceptual | FR-03 (9-value exit enum driving retry policy) | Not a library; provides classification pattern only |
| MCP (Model Context Protocol) | Standard | MIT | Active | Subprocess stdio protocol, JSON-RPC framing, tool lifecycle | Not designed for verdict routing; heavy for simple parser contract |
| Unix exit codes | Standard | — | Mature | FR-03 (0=success, non-zero=failure convention), Python subprocess support | Coarse granularity; 0/1-only tools lose nuance; no side-effect tracking |

## Evaluation

### Internal `shell` step pattern

- **Strengths:** Already exists, works today, proven in production. Run arbitrary commands, capture output. No new dependencies.
- **Weaknesses:** No verdict routing — user must manually implement label changes, issue closing, etc. No setup hooks. No timeout configuration. No environment variable mapping.
- **Integration effort:** Low — extend existing `run_shell_step` with optional verdict parser callback.
- **Cost:** None (already built).
- **Risks:** Minimal. Adding code to a working path risks regressions; mitigated by keeping the default path unchanged (NFR-02). Security: the existing shell step has no sandboxing — verdict parsers will need the new sandbox layer (NFR-03).
- **Forward compatibility:** High — no external dependency; changes are self-contained.

### flowai-workflow (korchasa/flowai-workflow)

- **Strengths:** Closest architectural match to the requirements. YAML-configured runtime per node (`claude`, `opencode`, `cursor`), timeout per node, extra CLI args forwarding. MIT licensed, actively maintained (0.7.15, April 2026).
- **Weaknesses:** Written in Deno/TypeScript, not Python. Integrating would require either a subprocess bridge or a language migration. No verdict parser abstraction (relies on exit code only). No sandboxing.
- **Integration effort:** High — would need to run as a sidecar or port to Python.
- **Cost:** Free (MIT), but has 8 weekly downloads — low community adoption.
- **Risks:** Low community adoption; JSR package ecosystem less established than npm/PyPI. Single maintainer risk. Security: no sandboxing — subprocesses inherit the host environment without restriction.
- **Forward compatibility:** Semantic versioning on JSR; upgrade within minor range should be safe.

### StackStorm runners

- **Strengths:** Mature, proven, Python-based (Apache 2.0). Pluggable runner system via stevedore (Python plugin loading). Runner metadata in YAML manifest files. Pre-defined runner types (local-shell, python, http, remote, workflow). ActionChain workflows. Sandboxed Python runner (virtualenv isolation). Active since 2014, 6k GitHub stars.
- **Weaknesses:** Heavy architecture — requires RabbitMQ, MongoDB, 12+ microservices for full deployment. The runner plugin system is tightly coupled to StackStorm's action execution lifecycle. Would need to extract just the runner abstraction, not viable as a dependency.
- **Integration effort:** Very high — cannot adopt as a library; would need to extract the runner abstraction pattern.
- **Cost:** Free (Apache 2.0).
- **Risks:** Architectural extraction is speculative; undocumented internals. Security: StackStorm uses virtualenv isolation for Python runners and provides user-scoped permission models — these patterns are informative for NFR-03 sandbox design but the full stack (RabbitMQ, MongoDB) introduces a large attack surface.
- **Forward compatibility:** N/A (pattern adoption only).

### cli-agent-spec ExitCode

- **Strengths:** Well-thought-out exit code table with machine-readable guarantees (retryable, side-effects). Defines codes for ARG_ERROR (2), PARTIAL_FAILURE (3), PRECONDITION (4), TIMEOUT (10), REDIRECTED (13). Hard invariants: code 2 always zero side effects, code 3 always non-retryable. Phase boundary between validation and execution.
- **Weaknesses:** Draft specification, not a library. Lacks stdin/stdout protocol design (no opinion on how parsers receive input). Focused on CLIs in general, not AI verdict specifically.
- **Integration effort:** Low — adopt the exit code table as the verdict parser contract.
- **Cost:** Free (MIT).
- **Risks:** Low community adoption (~5 GitHub stars); specification is not widely referenced. Could conflict with opencode's existing exit code convention (0=approved, 1=changes-requested, 2+=rejected). Single author risk — if abandoned, no community fork exists.
- **Forward compatibility:** Stable; spec changes would be additive.

### MCP (Model Context Protocol)

- **Strengths:** Standardized subprocess communication protocol (JSON-RPC over stdio). Used by Claude, Codex, Mastra, n8n. Well-documented transport specification. Strict rule: stdout is protocol traffic only, stderr for logs. This stdout/stderr separation is directly applicable to the parser sandbox design (NFR-03) — parsers should only read stdout, never stderr.
- **Weaknesses:** Designed for tool invocation, not verdict routing. JSON-RPC overhead for a simple exit-code + optional reason contract. Requires an MCP server per runtime.
- **Integration effort:** High — would need to implement an MCP client and wrap each runtime in an MCP server.
- **Cost:** Free (MIT).
- **Risks:** Misaligned abstraction level. Verdict parsing is simpler than MCP's full tool lifecycle. Security: MCP enforces stdout as protocol traffic with structured JSON-RPC framing, providing a hardened channel for subprocess communication; adopting this discipline strengthens the parser contract.
- **Forward compatibility:** Evolving standard; the stdio transport layer is stable, tool definitions change.

### pluggy

- **Strengths:** De facto Python plugin framework; used by pytest, tox, devpi. Simple hookspec/hookimpl decorator pattern. Well-documented with extensive production use. 4.5k+ GitHub stars, 200M+ downloads. Lightweight (no required dependencies).
- **Weaknesses:** Provides only plugin loading/dispatch — does not address subprocess management, sandboxing, or parser logic. Must be paired with other code for the full feature.
- **Integration effort:** Low — add as a dependency (3KB compressed) and define hookspecs for verdict parsers.
- **Cost:** Free (MIT).
- **Risks:** None significant. Mature, widely adopted, well-maintained by pytest-dev.
- **Forward compatibility:** Semantic versioning (stable since 1.0, currently 1.5). Breaking changes are extremely rare.

### sh, invoke, plumbum

- **Strengths:** `sh` (34M+ downloads) provides a Pythonic subprocess API with implicit `$PATH` resolution and timeout support. `invoke` (BSD, used by Fabric) provides subprocess execution with task abstraction. `plumbum` provides local and remote command execution with pipelines and timeouts.
- **Weaknesses:** `sh` is synchronous-only; `invoke` has a heavier task-runner footprint; `plumbum` adds remote-execution complexity. None provide verdict routing or plugin loading. All are alternatives to stdlib `subprocess`, which already covers the required functionality.
- **Integration effort:** Low to add any one, but unnecessary — Python's `subprocess` module covers all needed operations (run with timeout, env vars, capture stdout/stderr).
- **Cost:** Free (MIT/BSD).
- **Risks:** Dependency bloat. `sh` has had compatibility issues with newer Python versions. `invoke` and `plumbum` add abstractions that hide subprocess details we need direct control over (exit codes, sandboxing).
- **Forward compatibility:** All three are stable but evolve slowly.

## Recommendation

**Direction:** Build

The requirements are well-scoped and narrow: configure a different command, parse its exit code/stdout, optionally run a setup hook. No single library solves this in Python without bringing unnecessary weight or requiring a language/platform migration.

The right approach is a lightweight abstraction in `engine.py` and `run_rule.py`:

1. **Configurable `agent.command`** — add a `command` field to `AgentStep` dataclass. If absent, default to `["opencode", "run"]` (current behavior). If present, split on whitespace or accept a list. This is the same pattern as `runtime` in flowai-workflow's YAML config and mirrors how StackStorm's runners specify their `runner_type`.

2. **Verdict parser contract** — define a subprocess plugin interface: parser receives agent stdout on stdin, returns exit code 0 (approved), 1 (changes-requested), or 2+ (rejected/error). This follows Unix exit code conventions and aligns with the existing opencode convention. The cli-agent-spec ExitCode table provides a richer alternative for future expansion (retryable, side-effects annotations).

3. **Built-in parser for opencode** — the current behavior (rely on opencode's own exit codes) maps directly to the contract. Implement as a no-op passthrough: forward opencode's exit code as-is.

4. **Setup hooks** — run `agent.setup` as a subprocess before the agent command, abort on non-zero exit. This is simpler than StackStorm's `pre_run` lifecycle hooks but covers the use case.

5. **Built-in parsers for Codex and Gemini (FR-05)** — ship as Python functions that parse common output patterns (JSON verdict field, markdown section, YAML frontmatter). The verdict library (haizelabs) provides inspiration for structured output extraction but is overkill; a simple regex or JSON parse suffices.

6. **Distributable parsers (FR-09)** — use Python's importlib to load parser modules from a configurable path (`~/.config/opencode/parsers/`). This matches StackStorm's stevedore plugin pattern but at a simpler level.

## Sources of Information

- **flowai-workflow runtime selection**: YAML `runtime` field per node, `runtime_args` for extra CLI flags. Proves this config pattern works in production.
- **StackStorm runner plugin system**: Stevedore-based plugin loading from metadata YAML files. Pattern for `--list-runtimes` (FR-08) and parsers path loading (FR-09).
- **cli-agent-spec ExitCode**: Machine-readable exit code semantics (retryable, side-effects). Useful for a richer verdict contract in v2.
- **Structured Exit Reasons (JoelClaw)**: 9-value exit reason enum (`normal`, `timeout`, `budget_exceeded`, `permission_blocked`, etc.) driving retry policy. Pattern for error classification in custom parsers.
- **opencode-cli-enforcer**: Circuit breaker pattern per CLI (3 failures or 5 timeouts opens the circuit). Useful for reliability but out of scope for this feature.
- **MCP stdio transport**: Strict rule — stdout is protocol traffic, stderr is for logs. Adopt this convention for verdict parsers.
- **Safe IPC Patterns (Zylos Research)**: Pass payload via stdin not argv; validate JSON before acting on it; restrict subprocess environment. Directly applicable to NFR-03 (sandboxed parsers).
- **Verdict (haizelabs)**: Structured output extraction from LLM output. The `RegexExtractor` and `InstructorExtractor` patterns inform how built-in parsers for Codex/Gemini could work.
- **pluggy**: Hookspec/hookimpl plugin registration pattern for FR-09. Simpler than stevedore for the distributable parser path.
- **sh, invoke, plumbum**: Proven Python subprocess patterns (duration/timeout handling, env passthrough, exit code capture). Primarily confirm that stdlib `subprocess` is sufficient without adding dependencies.

## Open Questions

1. Should the verdict parser be a subprocess (standalone script/binary) as specified in FR-03, or could a simpler YAML-based config (map exit codes to verdicts) be offered as an alternative? A config-based parser would cover 80% of use cases without requiring users to write scripts.
2. What is the minimum contract for a verdict parser — does it receive the full agent stdout, or should it also receive step metadata (step name, workflow ID, github event) via env vars?
3. How should the engine discover which runtime corresponds to which built-in parser? Current approach: match by command basename (e.g., `codex` -> built-in Codex parser). Is this sufficient?
4. Should sandboxing (NFR-03) be implemented as a container per parser (e.g., bubblewrap, nsjail) or via Python subprocess sandbox flags (e.g., `subprocess.Popen` with restricted environment)?
5. Does `agent.command` need template expansion beyond `{{prompt_file}}`? Should it support `{{prompt}}` (inline prompt) and `{{env.VAR}}` (env var substitution)?

## Outcome

`verdict: approved`
