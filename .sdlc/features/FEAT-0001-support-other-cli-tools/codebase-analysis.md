---
issue: "#18"
title: "Support other harness CLI"
status: in-review
---

# Codebase Analysis: Support Other Harness CLI

## Overview

The engine (`llmaw`) is a single-executable Python CLI that routes GitHub events to rules and executes a pipeline per rule: pre-deterministic steps (`labels`/`shell`) -> agent step -> post-deterministic steps -> `on_outcome`. The agent step is currently hardcoded to invoke `opencode` with a fixed command pattern in `run_rule.py:_run_agent`. The requirements demand making this configurable: any CLI executable, a pluggable verdict parser, a pre-install setup hook, and per-runtime environment variables. The changeability outlook is good: the agent step is a thin call site with no internal state, and the existing coupling is limited to one dataclass (`AgentStep`), one serialization function (`agent_to_dict` / `rule_to_matrix`), one subprocess invocation (`_run_agent`), and one GitHub Actions workflow step (`Install opencode`).

## Scope of Analysis

**Entry points used:**

| Query | Path |
|---|---|
| Read all source files | `src/llm_augmented_workflows/{engine,run_rule,run_steps,apply_outcome,route,cli,sync_labels}.py` |
| Read test files | `tests/{test_engine,test_run_rule}.py` |
| Read workflow definitions | `.github/workflows/dispatch.yml`, `.github/wrappers/dispatch.yml` |
| Read flows config | `.github/llmaw/flows.yml` |
| Read documentation | `docs/flows.md` |

**Out of scope:** The `shell` step type (not being modified), GitHub Actions infrastructure (the reusable workflow and wrapper), and the skills repository (`tomzx/agents`).

## Relevant Existing Components

| Component | Path | Responsibility | Interaction |
|---|---|---|---|
| `AgentStep` dataclass | `src/llm_augmented_workflows/engine.py:39-45` | Hold parsed agent step config (kind, ref, model, agents_repository, timeout_minutes) | Extend — add `command`, `verdict_parser`, `setup`, `env` fields |
| `build_agent` | `src/llm_augmented_workflows/engine.py:152-180` | Resolve agent step overrides from step config, defaults, and base values | Extend — resolve new fields with same precedence (step > defaults > base) |
| `rule_to_matrix` / `agent_to_dict` | `src/llm_augmented_workflows/engine.py:325-349` | Serialize rule into JSON for the Actions matrix | Extend — include new agent fields in the serialized matrix |
| `_run_agent` | `src/llm_augmented_workflows/run_rule.py:49-56` | Invoke the agent CLI (`opencode run ...`) via `subprocess.run` | Replace — generalise to support any `command` with verdict routing |
| `_execute_rule` | `src/llm_augmented_workflows/run_rule.py:59-72` | Orchestrate the pipeline (pre -> agent -> post -> outcome) | Reuse as-is — pipeline ordering is unchanged |
| `run_shell` | `src/llm_augmented_workflows/run_steps.py:91-94` | Execute a shell script in a subprocess | Reuse as-is — setup hooks reuse the same subprocess pattern |
| `_read_outcome` (apply_outcome) | `src/llm_augmented_workflows/apply_outcome.py:29-42` | Read the `$OUTCOME_YAML` file the agent wrote | Reuse as-is — `on_outcome` routing is unchanged |
| `main` (run_rule) | `src/llm_augmented_workflows/run_rule.py:75-83` | Read matched rules from env/file and execute each | Reuse as-is — reading input and iterating rules is unchanged |
| `Install opencode` workflow step | `.github/workflows/dispatch.yml:129-141` | Install opencode CLI and clone agents repository | Replace — generalise to run `agent.setup` instead of hardcoded opencode install |
| `split_steps` | `src/llm_augmented_workflows/engine.py:107-144` | Split run steps into pre/agent/post/on_outcome | Reuse as-is — no change to step ordering or validation |
| CLI entrypoint (`cli.py`) | `src/llm_augmented_workflows/cli.py` | Parse subcommand and dispatch | Extend — add `--list-runtimes` flag (FR-08) |

## Dependency and Coupling Map

```
flows.yml
    |
    v
engine.py:load_flows / flatten_rules
    |
    v
engine.py:rule_to_matrix  ---> JSON (MATCHED_RULE / MATCHED_FILE)
    |
    v
run_rule.py:_execute_rule
    |
    |---> run_steps.py:apply_labels     (gh CLI)
    |---> run_steps.py:run_shell        (subprocess -> bash)
    |---> run_rule.py:_run_agent        (subprocess -> opencode [HARDCODED])
    |---> apply_outcome.py:apply        (reads $OUTCOME_YAML)
              |
              +---> run_steps.py:_gh    (gh CLI)
```

**Key coupling observations:**

1. **agent command is hardcoded in one place** — the `_run_agent` function in `run_rule.py:49-56` is the sole call site. No other module constructs the agent subprocess. This makes the blast radius small.

2. **Agent configuration flows through two serialization boundaries** — `AgentStep` -> `agent_to_dict` (Python -> JSON in the Actions matrix) -> `_run_agent` (JSON -> Python dict consumed by `subprocess.run`). The new fields must traverse this same path.

3. **`agent.command` maps to existing opencode install** — the workflow installs opencode unconditionally when `has_agent` is true. This install step must become conditional on the runtime choice.

4. **Verdict routing is already decoupled from the agent** — `on_outcome` reads `$OUTCOME_YAML` independently of how the agent produced it. The verdict parser only needs to translate the agent's stdout into the same `$OUTCOME_YAML` contract; the downstream routing is untouched.

5. **Synchronous boundary** — `subprocess.run` is blocking. The agent step holds the pipeline until completion. This is unchanged by the feature.

6. **Shared state via `$OUTCOME_YAML`** — the agent writes a YAML file; `apply_outcome.py` reads it. This is the only cross-component state. The verdict parser writes to it instead of the agent.

7. **Blast radius** — Changing `_run_agent` affects no other component. Changing `AgentStep` requires updating `build_agent`, `agent_to_dict`, and the workflow install step, but each is a local, additive change.

## Changeability Assessment

### `AgentStep` dataclass

- **Current state:** Frozen dataclass with 5 fields (kind, ref, model, agents_repository, timeout_minutes). Used only in `engine.py` and serialized via `agent_to_dict`.
- **Change disposition:** Extend
- **Rationale:** Add `command`, `verdict_parser`, `setup`, and `env` fields with `None` defaults. Existing consumers (`build_agent`, `agent_to_dict`) already iterate over fields; adding new fields is additive. The frozen dataclass ensures new fields are immutable once built.
- **Risk:** Low — pure data structure change with no behavioral impact on existing paths.
- **Constraints:** The existing 5 fields must remain present and behave identically (backward compatibility, NFR-02). Defaults for new fields must be `None` or equivalent so existing workflows produce identical serialization.

### `build_agent`

- **Current state:** Resolves model/agents_repository/timeout with precedence: step override > defaults > base. Accepts a dict from `flows.yml` and a `defaults` dict.
- **Change disposition:** Extend
- **Rationale:** Apply the same resolution pattern to the new fields. For `command`, the step-level value is already the final value (no base/default resolution needed beyond what the step dict already carries). For `env`, merge step-level env with defaults (if any). For `verdict_parser` and `setup`, step-level value only.
- **Risk:** Low — follows an established pattern.
- **Constraints:** The step-level dict (`value` in `build_agent`) currently uses `name`/`path`/`ref` as the ref identifier and passes everything else as `overrides`. New fields like `command` must be read from the correct location (not accidentally consumed as overrides or lost in the spread).

### `agent_to_dict`

- **Current state:** Returns a hardcoded dict of 5 fields matching `AgentStep`.
- **Change disposition:** Extend
- **Rationale:** Add the new fields to the serialized dict, filtering out `None` values to keep the matrix JSON compact and avoid sending unnecessary data to consumers that do not use them.
- **Risk:** Low — pure serialization change.
- **Constraints:** The dict must remain JSON-serializable (no non-JSON types). New fields with `None` defaults in `AgentStep` should be omitted from the output to preserve backward compatibility with existing `run_rule.py` consumers.

### `_run_agent`

- **Current state:** Constructs `["opencode", "run", "--model", ...]` and calls `subprocess.run(cmd, check=True)`. Throws on non-zero exit.
- **Change disposition:** Replace
- **Rationale:** The function must become runtime-aware: if `agent.command` is set, invoke that instead of the hardcoded opencode command. If a `verdict_parser` is configured, run the parser subprocess on the agent's stdout and map its exit code to the verdict contract. If `agent.setup` is set, run it as a subprocess before the agent. If `agent.env` is set, merge it into the subprocess environment. The existing behavior (when no new fields are set) must be identical (NFR-02).
- **Risk:** Medium — this is the highest-risk change. The subprocess invocation logic must handle command splitting/template expansion, timeout propagation (`timeout_minutes` already exists), stderr capture, and verdict parser orchestration. The existing `subprocess.run(cmd, check=True)` pattern must be preserved for the default path.
- **Constraints:**
  - Backward compatible at the default (`command=None` means opencode as today).
  - Must preserve the `check=True` behavior (raise on non-zero) for the default path.
  - Must support both string commands (shell-cmded via `shell=True`) and list commands.
  - Must NOT use `shell=True` by default (security constraint from existing code style).

### `Install opencode` workflow step

- **Current state:** GitHub Actions step that unconditionally installs opencode and clones the agents repository when any matched rule has an agent.
- **Change disposition:** Replace
- **Rationale:** When `agent.command` is configured to a non-opencode CLI, the opencode install is unnecessary. The workflow must instead run `agent.setup` (if configured) for each unique runtime. However, the workflow JSON currently only has `has_agent` (bool) — it does not know which runtime. The matrix entry must carry the runtime's setup command so the workflow step can execute it.
- **Risk:** Medium — the workflow step is in YAML (not Python), so it cannot reason about individual rules' agent configurations. The `has_agent` flag is a single boolean for all matched rules. If two matched rules use different runtimes, the workflow step must install both. The simplest approach is to add an `agent_setup` field to the matrix output (aggregated across all rules) so the workflow step can execute each unique setup command. Alternatively, defer all setup logic to `_run_agent` (run it in Python) and remove the workflow install step entirely.
- **Constraints:** Must not break existing workflows (no `agent.command`). Must not introduce a new workflow secret or permission.

### `Verdict parser` (new component)

- **Current state:** Does not exist. The agent's exit code is the de facto verdict: `subprocess.run(check=True)` means failure is an exception (non-zero exit causes the rule to fail). The exit code is not mapped to a verdict; only success/failure.
- **Change disposition:** Build new
- **Rationale:** FR-03 requires a pluggable verdict parser. The parser receives agent stdout on stdin and returns exit code 0 (approved), 1 (changes-requested), or 2+ (rejected/error). When no parser is configured, the default path preserves today's behavior (opencode's exit code passes through).
- **Risk:** Medium — the verdict parser contract must be carefully designed. The parser writes `$OUTCOME_YAML` with the verdict. This replaces the skill's own `$OUTCOME_YAML` write (for non-opencode runtimes that cannot write it). For opencode, the parser can be a no-op passthrough since opencode already writes `$OUTCOME_YAML` internally.
- **Constraints:** Exit code 0 = approved, 1 = changes-requested, 2+ = rejected/error (per requirements constraint).

### Built-in parsers for Codex and Gemini

- **Current state:** Do not exist.
- **Change disposition:** Build new (FR-05)
- **Rationale:** Each CLI produces stdout in a different format. Codex outputs JSON with a verdict field. Gemini CLI outputs markdown with a verdict section. Built-in parsers parse these formats into the standard verdict contract.
- **Risk:** Low — standalone Python functions with no dependencies. Each parser is a file in a `parsers/` submodule.
- **Constraints:** Must not import the CLI itself (not installed at parse time). Must handle missing/unexpected output gracefully (fallback to `rejected` / `unknown`).

### `_execute_rule` (pipeline orchestrator)

- **Current state:** Orchestrates pre -> agent -> post -> on_outcome. Calls `_run_agent`, then reads `$OUTCOME_YAML` in `apply`.
- **Change disposition:** Reuse as-is
- **Rationale:** The pipeline ordering is unchanged. `_run_agent` now handles the runtime-specific logic internally. `apply_outcome:apply` still reads `$OUTCOME_YAML` and routes on the verdict. The `OUTCOME_YAML` file is unlinked before each agent run (line 67) — this still works.
- **Risk:** None — no changes needed.

## Migration and Impact Considerations

### `_run_agent` (Replace)

**Path from current to target behavior:**

1. Default path (`command=None`): identical to today — invoke `["opencode", "run", "--model", ...]` with `subprocess.run(cmd, check=True)`. Keep the existing code path literally unchanged behind an `if command is None` guard.
2. Custom command path: parse `command` (string -> shlex split, list -> use as-is), merge `agent.env` into subprocess environment, run setup hook if present, invoke command, capture stdout/stderr, run verdict parser on stdout, write `$OUTCOME_YAML`, handle exit code.
3. Verdict parser: if `verdict_parser` is set, capture agent stdout, pipe to parser subprocess, read parser exit code, write `$OUTCOME_YAML`. If no parser, use the agent's own exit code and `$OUTCOME_YAML` (today's behavior for opencode).

**Backward compatibility:** The `command=None` path must produce identical behavior, including identical error output. Add a test that snapshots the current `subprocess.run` call arguments and asserts they match.

**Rollout strategy:** Add behind the new config fields only — no migration needed. Existing workflows omit these fields and get today's behavior.

**What else breaks:** Nothing. `_run_agent` is the only consumer of the agent config dict. Downstream pipeline stages (`apply_outcome`) are unaware of how the agent ran.

**De-risk:** Unit test the default path explicitly with argument capture. Integration test with a mock CLI that exercises the verdict parser contract.

### Install opencode workflow step (Replace)

**Two migration options:**

**Option A (defer to Python):** Remove the `Install opencode` step from the workflow entirely. Move setup logic into `_run_agent` itself: if `agent.setup` is set, run it before the agent. The opencode install becomes a setup script that flow authors must add to their flows if they use opencode. **Problem:** breaks existing workflows that rely on automatic opencode install.

**Option B (hybrid):** Keep the workflow step for opencode's automatic install. Add a new `agent_setup` field to the Actions matrix output that carries the setup command for each runtime (only when not opencode). The workflow step iterates unique setup commands. **Problem:** the workflow YAML must become smarter about installing per-runtime.

**Recommendation:** Start with Option B for backward compatibility. The workflow step conditionally runs setup commands from the matrix. A future release can migrate to Option A when all flows explicitly declare their setup.

### `AgentStep` fields (Extend)

**Field naming convention in flows.yml** (matching requirements):

```yaml
- skill: triage-feature
  command: codex
  env:
    API_KEY: sk-xxx
    MODEL: claude-3-5
  verdict_parser: /usr/local/bin/codex-parser
  setup: pip install codex-cli
```

Or at step level with the dict syntax:

```yaml
- skill:
    name: triage-feature
    command: codex
    env: { ... }
    verdict_parser: ...
    setup: ...
```

**Precedence:** Step-level `command` is the only meaningful level (no base/default). `env` merges step-level with any default env map. `setup` and `verdict_parser` are step-level only.

## Assumptions About Existing Code

- The opencode install (`curl -fsSL https://opencode.ai/install | bash`) creates an `opencode` binary on `PATH` that is then available in the `uv run` subprocess for `_run_agent`. If setup hooks are moved to `_run_agent`, the subprocess must inherit the parent's `PATH` (which it does by default with `subprocess.run`).
- The `$OUTCOME_YAML` contract is already well-defined: the skill writes it as its final action, and `apply_outcome.py` reads it. Verdict parsers can adopt this same contract.
- No rule currently uses more than one agent step. The `split_steps` validation enforces this.
- The `has_agent` boolean in the Actions matrix output is a single aggregate for all matched rules, not per-rule. If multiple rules with different runtimes match the same event, the current approach of a single install step is insufficient. However, this is an existing limitation (today all matched rules use opencode).

## Open Questions

1. How should the workflow install step discover which runtime(s) the matched rules need? The matrix output is a JSON array; should we add an `agent_setup` field per matrix entry and aggregate unique values in the workflow step?
2. Should `agent.command` accept a string (split by shell) or always require a list? If string, should we use `shlex.split` for safe parsing?
3. How should built-in parsers be registered and discovered? Simple match by command basename (e.g., `codex` -> built-in Codex parser) is the simplest approach. Is that sufficient, or do we need a registry dict?
4. Should the verdict parser receive step metadata (step name, workflow ID, event payload) via environment variables, or is the `$OUTCOME_YAML` writing contract sufficient? The requirements say parser receives agent stdout on stdin only, but metadata would enable richer parsers.
5. Can the `--list-runtimes` feature (FR-08) be resolved by scanning built-in parsers + user-defined parser path at startup, or does it need a registration mechanism?
