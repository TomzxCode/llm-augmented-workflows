---
issue: "#18"
title: "Support other harness CLI"
status: draft
---

# Specification: Support Other Harness CLI

## Overview

Add a configurable `agent.command` field to the agent step so flow authors can use any AI CLI runtime (Codex, Gemini CLI, Claude Code, etc.) instead of the hardcoded opencode invocation. A pluggable verdict parser contract maps the CLI's stdout/exit code to the engine's `$OUTCOME_YAML` protocol, preserving label-driven workflows for any runtime. Built-in parsers ship for Codex and Gemini CLI. The change is additive: existing workflows that omit `agent.command` behave identically to today.

## Architecture

```
flows.yml
    |
    v
engine.py: AgentStep ──── extended with command/verdict_parser/setup/env
    |
    v
engine.py: rule_to_matrix ──── new fields serialized into Actions matrix JSON
    |
    v
route.py ──── emits has_agent (unchanged) + new agent_setup (aggregated setup commands)
    |
    v
dispatch.yml
    |-- (if has_agent && no agent.command) Install opencode + skills (unchanged)
    |-- (if agent_setup) Run each unique setup command
    |
    v
run_rule.py: _run_agent ──── replaced with runtime-aware dispatcher
    |
    |-- [default: command=None] ──── opencode run ... (byte-identical to today)
    |-- [custom: command=...]
    |       |-- pre-flight validation (command exists on PATH)
    |       |-- template expansion ({{prompt}}, {{prompt_file}}, {{model}}, etc.)
    |       |-- setup hook (agent.setup subprocess)
    |       |-- agent execution with env vars (agent.env)
    |       |-- verdict parsing (agent.verdict_parser or built-in or exit-code)
    |       |-- $OUTCOME_YAML written by engine
    |
    v
apply_outcome.py ──── reads $OUTCOME_YAML (unchanged)
```

### Component Relationships

| Component | Responsibility | Change |
|---|---|---|
| `engine.py:AgentStep` | Data model for agent step config | Extend — 4 new optional fields |
| `engine.py:build_agent` | Resolve agent fields with precedence | Extend — resolve new fields |
| `engine.py:agent_to_dict` / `rule_to_matrix` | Serialize rule for Actions matrix | Extend — include new fields |
| `route.py` | Emit workflow outputs (has_agent, agent_setup) | Extend — add agent_setup aggregate |
| `dispatch.yml` | GitHub Actions workflow steps | Replace — conditional install + setup steps |
| `run_rule.py:_run_agent` | Execute agent subprocess and route verdict | Replace — runtime-aware dispatcher |
| `run_rule.py:_execute_rule` | Pipeline orchestrator | Reuse — unchanged |
| `apply_outcome.py:apply` | Read $OUTCOME_YAML and apply on_outcome | Reuse — unchanged |
| `run_steps.py:run_shell` | Shell subprocess helper | Reuse — setup hooks reuse same pattern |
| `cli.py` | CLI entrypoint | Extend — add --list-runtimes flag (FR-08) |
| `parsers/` (new submodule) | Built-in verdict parsers (Codex, Gemini) | Build new |
| `parsers/discovery.py` (new) | Parser auto-discovery from parsers path | Build new |

## Data Models

### AgentStep (extended)

| Field | Type | Constraints | Description |
|---|---|---|---|
| kind | string | not null, "skill" or "prompt" | Step type |
| ref | string | not null | Skill name, path, or prompt ref |
| model | string | not null | Model identifier |
| agents_repository | string | not null | Owner/repo providing skills |
| timeout_minutes | int or None | null = no timeout | Agent subprocess timeout |
| command | string or None | null = use opencode | CLI command or command template; string values are shlex-split, support `{{...}}` template expansion |
| verdict_parser | string or None | null = auto-detect (built-in or exit-code-only) | Path to verdict parser executable; receives agent stdout on stdin, returns exit code 0/1/2+ |
| setup | string or None | null = no setup hook | Shell script or command to run before the agent install/verify the CLI; runs as subprocess, abort on non-zero exit |
| env | dict[str,str] or None | null = no extra env vars | Key-value pairs set as environment variables in the agent subprocess |

### Rule (unchanged)

The Rule dataclass is unchanged. It holds an `AgentStep` instance as its `agent` field, which now carries the new optional fields.

### Route Output (extended)

| Field | Type | Description |
|---|---|---|
| matched | JSON array | Matched rule matrix entries |
| count | string | Number of matched rules |
| has_agent | string | "True" if any matched rule has an agent step |
| agent_setup | string | JSON array of unique `agent.setup` values across all matched rules; empty `[]` when none needed |

### $OUTCOME_YAML (engine-written for custom commands)

The engine writes `$OUTCOME_YAML` for custom commands. The file is a YAML mapping with a single `verdict` key. The file path is `$OUTCOME_YAML` (same env var opencode uses today). For the default opencode path, opencode writes the file itself and the engine does not touch it.

| Field | Type | Values | Description |
|---|---|---|---|
| verdict | string | "approved", "changes-requested", "rejected" | Routing verdict mapped from parser exit code |

**Verdict mapping:**

| Parser exit code | Verdict |
|---|---|
| 0 | approved |
| 1 | changes-requested |
| 2+ (any non-zero) | rejected |

### Built-in Parser Registry

Conceptual mapping of command basename to parser module. The registry is checked when `verdict_parser` is unset and `command` is set.

| Command basename | Parser | Source |
|---|---|---|
| opencode | none (opencode writes $OUTCOME_YAML itself) | built-in default |
| codex | `parsers/codex.py` | built-in (FR-05) |
| gemini | `parsers/gemini.py` | built-in (FR-05) |
| any other | scanned from `~/.config/opencode/parsers/` by basename match | user-installed (FR-09) |

## API Contracts

### Agent Configuration (flows.yml)

The agent step accepts new fields at the step level. When `command` is unset, the engine invokes opencode with the current hardcoded command pattern.

**String command syntax (shlex-split):**

```yaml
- skill: triage
  command: codex --prompt {{prompt_file}}
  env:
    CODEX_API_KEY: sk-xxx
  setup: pip install codex-cli
```

**List command syntax (used as-is):**

List syntax is not supported in YAML flow config; use string syntax only. The engine splits strings with `shlex.split`.

**Template expansion variables:**

| Variable | Description | Example |
|---|---|---|
| `{{prompt}}` | Inline prompt text (for prompt-kind steps) | `claude -p "{{prompt}}"` |
| `{{prompt_file}}` | Path to a temp file holding the prompt text | `gemini --file {{prompt_file}}` |
| `{{model}}` | Resolved model name | `--model {{model}}` |
| `{{ref}}` | Step ref (skill name or prompt path) | `opencode run --command {{ref}}` |
| `{{kind}}` | Step kind ("skill" or "prompt") | Echoed to CLI for runtime routing |
| `{{env.VAR}}` | Any env var from `agent.env` or process env | `--api-key {{env.API_KEY}}` |

**Full step example with all new fields:**

```yaml
- skill:
    name: triage-feature
    command: codex --model {{model}} --file {{prompt_file}}
    verdict_parser: /usr/local/bin/codex-parser
    setup: |
      pip install codex-cli
    env:
      CODEX_API_KEY: sk-xxx
      CODEX_MODEL: claude-3-5-sonnet
    timeout_minutes: 10
```

### Verdict Parser Contract

The verdict parser is a subprocess plugin interface:

| Aspect | Contract |
|---|---|
| Input | Agent stdout piped to parser stdin |
| Output | Exit code 0, 1, or 2+ |
| Exit 0 | "approved" |
| Exit 1 | "changes-requested" |
| Exit 2+ | "rejected" / error |
| Timeout | 30s default, configurable per step |
| Sandbox | No network access by default; restricted environment (minimal PATH, dropped GH_TOKEN) |
| Stdout | Parser stdout is ignored |
| Stderr | Parser stderr is logged at WARNING level |
| Side effects | Parser must not write to disk; the engine owns `$OUTCOME_YAML` |

**Config-based alternative (future, open question):** A simpler YAML-based verdict parser — map exit codes directly to verdicts — may cover 80% of use cases without requiring users to write scripts. This is noted as a deferred decision.

### CLI Changes

The `llmaw` CLI gains a new subcommand:

```
llmaw --list-runtimes

Registered runtimes:
  opencode   (built-in, no parser needed)
  codex      (built-in parser: parsers/codex.py)
  gemini     (built-in parser: parsers/gemini.py)
  my-cli     (user parser: ~/.config/opencode/parsers/my-cli)
```

## Sequences

### Default Path (command=None) — No Change

```
_execute_rule
    |
    |-- _run_agent(agent):  # command is None
    |       |-- cmd = ["opencode", "run", "--model", model, ...]
    |       |-- subprocess.run(cmd, check=True)  # opencode writes $OUTCOME_YAML
    |       |-- return (opencode exit code propagated)
    |
    |-- apply($OUTCOME_YAML)  # reads opencode's file, routes on verdict
```

Byte-identical to today. The `if command is None` branch preserves the existing code path literally.

### Custom Command Path (command=...)

```
_execute_rule
    |
    |-- _run_agent(agent):  # command is "codex --file {{prompt_file}}"
    |       |
    |       |-- PRE-FLIGHT: validate "codex" exists on PATH
    |       |       if not found: raise FileNotFoundError with PATH detail
    |       |
    |       |-- SETUP: if agent.setup is set
    |       |       subprocess.run(["bash", "-c", setup], check=True)
    |       |       if non-zero: abort with setup failure error
    |       |
    |       |-- TEMPLATE EXPANSION:
    |       |       prompt_text = read(agent.ref) if kind=="prompt" else ""
    |       |       prompt_file = tempfile.NamedTemporaryFile(delete=False)
    |       |       prompt_file.write(prompt_text)
    |       |       command = agent.command
    |       |           .replace("{{prompt_file}}", prompt_file.path)
    |       |           .replace("{{prompt}}", shlex.quote(prompt_text))
    |       |           .replace("{{model}}", agent.model)
    |       |           .replace("{{ref}}", agent.ref)
    |       |           .replace("{{kind}}", agent.kind)
    |       |       # {{env.VAR}} resolved per VAR in agent.env or os.environ
    |       |       cmd = shlex.split(command)  # or use as-is if already list
    |       |
    |       |-- EXECUTION:
    |       |       env = os.environ.copy()
    |       |       if agent.env: env.update(agent.env)
    |       |       log.debug("running agent command: %s", cmd)
    |       |       result = subprocess.run(
    |       |           cmd,
    |       |           capture_output=True,
    |       |           text=True,
    |       |           env=env,
    |       |           timeout=agent.timeout_minutes*60 or None,
    |       |       )
    |       |       log.debug("agent exit code: %d", result.returncode)
    |       |
    |       |-- VERDICT PARSING:
    |       |       parser = agent.verdict_parser
    |       |           or discover_builtin_parser(cmd[0])
    |       |           or discover_user_parser(cmd[0])
    |       |       if parser:
    |       |           parser_result = subprocess.run(
    |       |               [parser],
    |       |               input=result.stdout,
    |       |               capture_output=True,
    |       |               timeout=30,  # parser timeout
    |       |           )
    |       |           verdict = map_exit_code(parser_result.returncode)
    |       |       else:
    |       |           # fallback: exit-code-only parsing
    |       |           verdict = "approved" if result.returncode == 0 else "rejected"
    |       |       write_outcome_yaml(verdict)
    |       |
    |       |-- CLEANUP: delete temp prompt file (finally block)
    |
    |-- apply($OUTCOME_YAML)  # reads engine's file, routes on verdict
```

### Built-in Parser Discovery

```
discover_parser(command_basename):
    1. Check built-in registry: {"codex": codex_parser, "gemini": gemini_parser}
    2. If match: return built-in parser path
    3. Scan ~/.config/opencode/parsers/ for file matching basename
    4. If match: return user parser path
    5. Otherwise: return None (fall back to exit-code-only)
```

Built-in parsers win over user parsers for the same name, so the engine's parsers are always authoritative.

### Workflow Install Steps (Option B — Hybrid)

```
dispatch.yml before:
    has_agent? -> Install opencode -> Install skills -> Run rules

dispatch.yml after:
    has_agent?
        |-- (no agent.command configured) -> Install opencode + Install skills (unchanged)
        |-- (agent_setup non-empty)
        |       For each unique setup command:
        |           run setup command
        |-- Run rules
```

The `route` step emits an `agent_setup` JSON array containing unique `agent.setup` values. The workflow iterates these. The existing `Install opencode` and `Install skills` steps become conditional: they only run when no rule has `agent.command` configured (detected by checking if `agent_setup` is empty and `has_agent` is true).

## Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Verdict parser interface | Subprocess (exit code + stdin) | Keeps the contract language-agnostic, sandboxable, and simple. No in-process Python loading of untrusted code. |
| `$OUTCOME_YAML` ownership | Engine writes it for custom commands; opencode writes it for default | Preserves backward compatibility while keeping the parser contract minimal (no file system side effects). |
| Template expansion | String replacement before shlex.split | Ensures multi-word values (e.g., `{{prompt}}` with spaces) expand correctly within a single token. |
| Command validation | Fail fast on missing executable | Clear error message with PATH detail, no silent fallback to opencode. |
| Setup hooks | Subprocess in _run_agent (Python side), not workflow YAML | Avoids coupling the workflow definition to runtime-specific install logic. Hybrid approach keeps opencode's automatic install for default path. |
| Built-in parser vs exit-code-only | Exit-code-only fallback when no parser is configured or discovered | Covers the "I just want to run a different CLI" case without requiring users to write parser scripts. |
| Parser discovery | Basename match (command basename -> parser filename) | Simple, predictable, no registration step needed. |
| No new dependencies | stdlib `subprocess`, `shlex`, `tempfile`, `importlib` only | The requirements are narrow and well-covered by the Python standard library. |
| Backward compatibility | `command=None` preserves byte-identical behavior | The existing `subprocess.run(cmd, check=True)` call is preserved behind an explicit guard. |

## Risks and Unknowns

1. **Template expansion edge cases** — `{{prompt}}` with very large prompt text (multi-kilobyte) may exceed CLI argument length limits. Document that `{{prompt_file}}` is the recommended approach for large prompts. Shell metacharacters in expanded values (e.g., prompt text containing quotes) must be handled via `shlex.quote` before inline substitution.

2. **Subprocess lifecycle** — Two-level subprocess (agent + parser) with independent timeouts. Agent timeout kills the agent but the parser must not be affected. Signal propagation (SIGTERM -> agent, not parser) must be explicit.

3. **Sandboxing approach** — NFR-03 requires sandboxed parsers. Initial implementation restricts the subprocess environment (drop `GH_TOKEN`, minimal `PATH`). Container-based isolation (bubblewrap, nsjail) is a hardening option for a future iteration. The parser interface is designed so container wrapping is a transparent addition later.

4. **Built-in parser fragility** — Codex and Gemini CLI output formats may change across versions. Built-in parsers must fail gracefully (default to "rejected") when output cannot be parsed, with a logged warning.

5. **Multi-rule runtime conflict** — If two matched rules use different runtimes, the workflow must install both. The `agent_setup` aggregate in the route output handles this, but the "Install opencode" step becomes a special case that only runs when no custom command is configured.

6. **Windows compatibility** — Template expansion uses `shlex.split` (Unix-style quoting). Windows paths with spaces or backslashes require testing. The codebase currently targets Linux runners only.

7. **Config-based verdict parser (deferred)** — A YAML-based parser (map exit codes to verdicts) would cover most use cases without requiring users to write scripts. This is deferred to a follow-up feature.

## Out of Scope

- The `shell` step type is not modified.
- Container-based sandboxing for verdict parsers is deferred.
- Remote/SSH command execution is not supported.
- The reusable workflow caller (`.github/wrappers/dispatch.yml`) is not modified.
- Per-runtime sandbox configuration (fine-grained network access per runtime) is deferred.
- Inline YAML-based verdict parsers (config-based, no script) are deferred.
- Admin-enforced allowlist of approved `agent.command` values is deferred.
- Circuit breaker or retry patterns for agent subprocess failures are deferred.
