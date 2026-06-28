---
issue: "#18"
title: "Support other harness CLI"
status: in-review
revision: 2
---

# Codebase Analysis: Support Other Harness CLI

## Overview

The engine (`llmaw`) is a single-executable Python CLI that routes GitHub events to rules and executes a pipeline per rule: pre-deterministic steps (`labels`/`shell`) -> agent step -> post-deterministic steps -> `on_outcome`. The agent step is currently hardcoded to invoke `opencode` with a fixed command pattern in `run_rule.py:_run_agent`. The requirements demand making this configurable: any CLI executable, a pluggable verdict parser, a pre-install setup hook, per-runtime environment variables, command validation, distributable parsers, sandboxed execution, and structured logging. The changeability outlook is good: the agent step is a thin call site with no internal state, and the existing coupling is limited to one dataclass (`AgentStep`), one serialization function (`agent_to_dict` / `rule_to_matrix`), one subprocess invocation (`_run_agent`), and two GitHub Actions workflow steps (`Install opencode`, `Install skills`).

## Scope of Analysis

**Entry points used:**

| Query | Path |
|---|---|
| Read all source files | `src/llm_augmented_workflows/{engine,run_rule,run_steps,apply_outcome,route,cli,sync_labels}.py` |
| Read test files | `tests/{test_engine,test_run_rule}.py` |
| Read workflow definitions | `.github/workflows/dispatch.yml`, `.github/wrappers/dispatch.yml` |
| Read documentation | `docs/flows.md` |

**Out of scope:** The `shell` step type (not being modified), the reusable workflow caller (`.github/wrappers/dispatch.yml` is a thin passthrough), and the skills repository (`tomzx/agents`).

## Relevant Existing Components

| Component | Path | Responsibility | Interaction |
|---|---|---|---|
| `AgentStep` dataclass | `src/llm_augmented_workflows/engine.py:39-45` | Hold parsed agent step config (kind, ref, model, agents_repository, timeout_minutes) | Extend — add `command`, `verdict_parser`, `setup`, `env` fields |
| `build_agent` | `engine.py:152-180` | Resolve agent step overrides from step config, defaults, and base values | Extend — resolve new fields with same precedence (step > defaults > base) |
| `rule_to_matrix` / `agent_to_dict` | `engine.py:325-349` | Serialize rule into JSON for the Actions matrix | Extend — include new agent fields in the serialized matrix |
| `_run_agent` | `run_rule.py:49-56` | Invoke the agent CLI (`opencode run ...`) via `subprocess.run` | Replace — generalise to support any `command` with verdict routing, validation, setup hooks, env vars, logging, and timeout |
| `_execute_rule` | `run_rule.py:59-72` | Orchestrate the pipeline (pre -> agent -> post -> outcome) | Reuse as-is — pipeline ordering is unchanged |
| `run_shell` | `run_steps.py:91-94` | Execute a shell script in a subprocess | Reuse as-is — setup hooks reuse the same subprocess pattern |
| `apply` (apply_outcome) | `apply_outcome.py:56-90` | Read `$OUTCOME_YAML` and apply the matched `on_outcome` action | Reuse as-is — `on_outcome` routing is unchanged |
| `main` (run_rule) | `run_rule.py:75-83` | Read matched rules from env/file and execute each | Reuse as-is — reading input and iterating rules is unchanged |
| `Install opencode` workflow step | `.github/workflows/dispatch.yml:129-131` | Install opencode CLI when `has_agent == 'true'` | Replace — generalise to run `agent.setup` instead of hardcoded opencode install |
| `Install skills` workflow step | `.github/workflows/dispatch.yml:133-140` | Clone agents repository and symlink skills | Replace — becomes conditional; only runs when the runtime requires it, or deferred to `agent.setup` |
| `split_steps` | `engine.py:107-144` | Split run steps into pre/agent/post/on_outcome | Reuse as-is — no change to step ordering or validation |
| CLI entrypoint (`cli.py`) | `cli.py:15-43` | Parse subcommand and dispatch | Extend — add `--list-runtimes` flag (FR-08) |
| `route` output (`has_agent`) | `route.py:68` | Emit `has_agent` boolean for the workflow step | Extend — also emit aggregated `agent_setup` commands for the workflow |
| Verdict parser (new) | `_run_agent` or new `parsers/` submodule | Read agent stdout on stdin, return exit code 0/1/2+ | Build new — subprocess plugin interface |
| Built-in parsers (Codex, Gemini) | New `parsers/` submodule | Parse CLI-specific stdout formats into verdict exit codes | Build new — standalone Python functions |
| Parser discovery (FR-09) | New mechanism | Load parser scripts from a configurable directory path | Build new — `importlib` or subprocess exec |

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

1. **agent command is hardcoded in one place** — `_run_agent` in `run_rule.py:49-56` is the sole call site. No other module constructs the agent subprocess. The blast radius is small.

2. **Agent configuration flows through two serialization boundaries** — `AgentStep` -> `agent_to_dict` (Python -> JSON in the Actions matrix) -> `_run_agent` (JSON -> Python dict consumed by `subprocess.run`). New fields must traverse this same path.

3. **Workflow install steps are hardcoded** — `dispatch.yml:129-140` unconditionally installs opencode and clones the agents repo when `has_agent` is true. These steps must become conditional on the runtime choice or be deferred to `agent.setup`.

4. **Verdict routing is already decoupled from the agent** — `on_outcome` reads `$OUTCOME_YAML` independently of how the agent produced it. The verdict parser translates the agent's stdout into the same `$OUTCOME_YAML` contract; the downstream routing is untouched.

5. **Synchronous boundary** — `subprocess.run` is blocking. The agent step holds the pipeline until completion. This is unchanged by the feature.

6. **Shared state via `$OUTCOME_YAML`** — the agent writes a YAML file; `apply_outcome.py` reads it. This is the only cross-component state. For the default (opencode) path, opencode writes it directly. For custom commands, the engine writes it after parsing the agent's exit code.

7. **Blast radius** — Changing `_run_agent` affects no other component. Changing `AgentStep` requires updating `build_agent`, `agent_to_dict`, and the workflow install steps, but each is a local, additive change.

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
- **Rationale:** Apply the same resolution pattern to the new fields. For `command`, the step-level value is already the final value (no base/default resolution needed). For `env`, merge step-level env with defaults (if any). For `verdict_parser` and `setup`, step-level value only.
- **Risk:** Low — follows an established pattern.
- **Constraints:** The step-level dict (`value` in `build_agent`) currently uses `name`/`path`/`ref` as the ref identifier and passes everything else as `overrides`. New fields like `command` must be read from the correct location (not accidentally consumed as overrides or lost in the spread).

### `agent_to_dict`

- **Current state:** Returns a hardcoded dict of 5 fields matching `AgentStep`.
- **Change disposition:** Extend
- **Rationale:** Add the new fields to the serialized dict, filtering out `None` values to keep the matrix JSON compact and avoid sending unnecessary data to consumers that do not use them.
- **Risk:** Low — pure serialization change.
- **Constraints:** The dict must remain JSON-serializable (no non-JSON types). New fields with `None` defaults in `AgentStep` should be omitted from the output to preserve backward compatibility.

### `_run_agent`

- **Current state:** Constructs `["opencode", "run", "--model", ...]` and calls `subprocess.run(cmd, check=True)`. Throws on non-zero exit. No pre-execution validation. No logging of the command or exit code beyond the generic `log.info` of kind/ref.
- **Change disposition:** Replace
- **Rationale:** The function must become runtime-aware on multiple axes:
  - **Command selection:** if `agent.command` is set, invoke that instead of the hardcoded opencode command. String commands are split with `shlex.split` (never `shell=True`). List commands are used as-is.
  - **Template expansion (FR-01):** if `agent.command` is a string containing `{{...}}` placeholders, expand them before splitting. Supported variables: `{{prompt}}` (the prompt text for `prompt`-kind steps), `{{prompt_file}}` (path to a temp file holding the prompt text), `{{model}}` (resolved model name), `{{ref}}` (step ref — skill name or prompt path), `{{kind}}` (step kind: `skill` or `prompt`), and `{{env.VAR}}` (any environment variable from `agent.env` or the process env). Unknown placeholders are left as-is (so external tools like shell formatters can use their own syntax).
  - **Pre-execution validation (FR-06):** if `agent.command` is set, validate the executable exists on `PATH` (or the full path is resolvable) before invoking. After template expansion, validate the first token of the resolved command. Fail fast with a clear error listing the command name and the directories searched.
  - **Setup hooks (FR-04):** if `agent.setup` is set, run it as a subprocess before the agent, aborting if it exits non-zero.
  - **Environment variables (FR-07):** if `agent.env` is set, merge it into the subprocess environment.
  - **Verdict parser (FR-03):** if `agent.verdict_parser` is set, capture agent stdout, pipe to parser subprocess, read parser exit code. Map exit code to `$OUTCOME_YAML` internally (engine writes the file, not the parser). Default: use the agent's own exit code and its `$OUTCOME_YAML` output (preserving today's behavior for opencode).
  - **Timeout (NFR-01):** use the existing `timeout_minutes` for the agent command. Apply a separate 30s default timeout for the verdict parser subprocess.
  - **Logging (NFR-04):** log the configured agent command at DEBUG before execution and the exit code at DEBUG after execution.
  - **Backward compatibility (NFR-02):** when `command` is `None`, behavior must be byte-identical to today.
- **Risk:** Medium — the subprocess invocation logic must handle template expansion (variable substitution with proper escaping and temp file lifecycle), command splitting, timeout propagation (two levels: agent + parser), stderr capture, verdict parser orchestration, and pre-flight validation.
- **Constraints:**
  - Backward compatible at the default (`command=None` means opencode as today).
  - String commands are shlex-split; list commands used as-is. Never use `shell=True` by default.
  - Template expansion happens before `shlex.split`, so `{{prompt}}` with spaces expands correctly.
  - Must preserve `subprocess.run(cmd, check=True)` behavior for the default path (opencode).
  - Must surface stderr on error for any failing subprocess.
  - Must not import or require the configured CLI at engine install time.

### Verdict parser (new subprocess contract)

- **Current state:** Does not exist. The agent's exit code is the de facto verdict: `subprocess.run(check=True)` means failure is an exception (non-zero exit causes the rule to fail). No structured verdict mapping.
- **Change disposition:** Build new
- **Rationale:** FR-03 requires a pluggable verdict parser. The parser receives agent stdout on stdin, returns exit code 0 (approved), 1 (changes-requested), or 2+ (rejected/error). The engine maps the exit code to `$OUTCOME_YAML` internally (writes the YAML file with `verdict:` based on the exit code). For the default path (opencode), the engine skips the parser and relies on opencode's own `$OUTCOME_YAML` output. Custom parsers do NOT write `$OUTCOME_YAML` themselves — the engine owns that contract.
- **Risk:** Medium — the verdict parser contract must handle sandboxing (NFR-03), timeout (NFR-01, 30s default), and graceful degradation (malformed parser, missing parser, parser crash).
- **Constraints:**
  - Exit code 0 = approved, 1 = changes-requested, 2+ = rejected/error.
  - Parser receives stdin only (agent stdout). No step metadata via env vars initially.
  - Parser subprocess must be sandboxed: no network access by default (NFR-03). Implementation options: `subprocess.Popen` with restricted environment (dropping `GH_TOKEN`, `PATH` minimal), or container-based (bubblewrap/nsjail). Start with environment restriction; escalate to container if security review requires it.
  - Parser must complete within 30s (configurable per step, default 30s). Kill and report timeout if exceeded.
  - Parser must not have access to the agent's working directory or output files beyond what is piped on stdin.

### Built-in parsers for Codex and Gemini (FR-05)

- **Current state:** Do not exist.
- **Change disposition:** Build new
- **Rationale:** Each CLI produces stdout in a different format. Codex outputs JSON with a verdict field. Gemini CLI outputs markdown with a verdict section. Built-in parsers parse these formats into the standard verdict exit code contract.
- **Risk:** Low — standalone Python functions with no external dependencies. Each parser is a file in a `parsers/` submodule. Graceful fallback: if output cannot be parsed, exit 2+ (rejected/error).
- **Constraints:** Must not import the CLI itself (not installed at engine install time). Must handle missing/unexpected output gracefully.

### Parser discovery path (FR-09)

- **Current state:** Does not exist.
- **Change disposition:** Build new
- **Rationale:** FR-09 requires user-installed parsers to be loaded from a configurable `parsers.path` directory (default `~/.config/opencode/parsers/`). When `agent.verdict_parser` is unset and `agent.command` is set, the engine should discover a parser by matching the command basename against filenames in the parsers path. Built-in parsers ship in the engine's `parsers/` submodule and are checked first (built-in wins over user-installed for the same name). User parsers are executables found on the parsers path.
- **Risk:** Low — file-system scan with filename matching. No heavy dependency. Parser scripts are invoked as subprocesses (same contract as explicit `verdict_parser`), so there is no in-process Python loading risk from untrusted parser scripts.
- **Constraints:** Must not import or exec untrusted Python code from the parsers path. Parser scripts are always invoked as subprocesses. The parsers path must be user-configurable via an environment variable or engine config (default `~/.config/opencode/parsers/`). The path must not require elevated privileges to read.

### `Install opencode` and `Install skills` workflow steps

- **Current state:** Two hardcoded GitHub Actions steps in `dispatch.yml:129-140` that run unconditionally when any matched rule has an agent. They install opencode via curl and clone the agents repository.
- **Change disposition:** Replace
- **Rationale:** When `agent.command` is configured to a non-opencode CLI, the opencode install is unnecessary. The workflow must instead run `agent.setup` (if configured) for each unique runtime. However, the workflow step currently only has `has_agent` (bool) — it does not know which runtime. The matrix entry must carry the runtime's setup command so the workflow step can execute it.
- **Risk:** Medium — the workflow step is in YAML (not Python), so it cannot reason about individual rules' agent configurations. `has_agent` is a single boolean for all matched rules. If two matched rules use different runtimes, the workflow step must install both. The simplest approach is to add an `agent_setup` field to the workflow output (aggregated across all rules) so the workflow step can execute each unique setup command. An alternative is to defer all setup logic to `_run_agent` (run it in Python) and remove the workflow install steps entirely.
- **Constraints:** Must not break existing workflows (no `agent.command`). Must not introduce a new workflow secret or permission. The `Install skills` step must still run for opencode workflows.

### `_execute_rule` (pipeline orchestrator)

- **Current state:** Orchestrates pre -> agent -> post -> on_outcome. Calls `_run_agent`, then reads `$OUTCOME_YAML` in `apply`.
- **Change disposition:** Reuse as-is
- **Rationale:** The pipeline ordering is unchanged. `_run_agent` now handles the runtime-specific logic internally. `apply_outcome:apply` still reads `$OUTCOME_YAML` and routes on the verdict. The `OUTCOME_YAML` file is unlinked before each agent run (`run_rule.py:67`) — this still works because for custom commands, `_run_agent` writes `$OUTCOME_YAML` internally after parsing.
- **Risk:** None — no changes needed.

### `route` output (`has_agent`)

- **Current state:** Emits `has_agent` (bool) and `matched` (JSON array) as workflow outputs at `route.py:66-68`. Also writes the matched matrix to `MATCHED_FILE`.
- **Change disposition:** Extend
- **Rationale:** Add an aggregated `agent_setup` output that collects unique `agent.setup` values across all matched rules. This allows the workflow to install only the runtimes actually needed. If a rule has no `agent.setup` but has `agent.command` set, emit nothing (the setup is assumed to be handled by external means or by `_run_agent`'s deferred setup logic).
- **Risk:** Low — additive change to the route output. Existing consumers ignore the new field.
- **Constraints:** The output value must be a JSON list (unique setup commands). Empty list when no setup is needed.

## Migration and Impact Considerations

### `_run_agent` (Replace)

**Path from current to target behavior:**

1. **Default path** (`command` is `None`): identical to today — invoke `["opencode", "run", "--model", ...]` with `subprocess.run(cmd, check=True)`. Keep the existing code path literally unchanged behind an `if command is None` guard. opencode writes `$OUTCOME_YAML` itself; the engine does not intervene.

2. **Custom command path** (`command` is set):
   - Pre-flight: validate command exists on `PATH` (or is a valid absolute path). Fail fast with a clear error.
   - Setup: if `agent.setup` is set, run as subprocess with `check=True`. Abort on failure.
   - Template expansion: replace `{{prompt}}` with the prompt text (for `prompt`-kind steps), `{{prompt_file}}` with the path to a temporary file holding the prompt (created before execution, cleaned up after), `{{model}}`/`{{ref}}`/`{{kind}}` with their resolved values, and `{{env.VAR}}` with the corresponding env var from `agent.env` or process environment. Unknown placeholders are left verbatim. Expansion runs before `shlex.split`.
   - Execute: parse expanded `command` (string -> `shlex.split`, list -> use as-is), merge `agent.env` into subprocess environment, invoke with `subprocess.run(cmd, capture_output=True, timeout=timeout_minutes)`.
   - Parsing: if `verdict_parser` is set, pipe agent stdout to parser subprocess with 30s timeout, read parser exit code. Map to `$OUTCOME_YAML` (`verdict: approved` / `changes-requested` / `rejected`) and write the YAML file.
   - Default parsing: if no `verdict_parser`, rely on the agent's own exit code: 0 = approved, non-zero = rejected. Write `$OUTCOME_YAML` with this mapping. The agent's own `$OUTCOME_YAML` output (if any) is ignored — the engine owns the file for custom commands.
   - Logging: log the resolved (expanded) command at DEBUG before execution. Log exit code at DEBUG after execution.

**Backward compatibility:** The `command=None` path must produce identical behavior, including identical error output. The existing `subprocess.run(cmd, check=True)` call should be preserved as the default branch. Add a test that snapshots the current call arguments and asserts they match.

**Rollout strategy:** Add behind the new config fields only — no migration needed. Existing workflows omit these fields and get today's behavior.

**What else breaks:** Nothing. `_run_agent` is the only consumer of the agent config dict. Downstream pipeline stages (`apply_outcome`) are unaware of how the agent ran.

**De-risk:** Unit test the default path explicitly with argument capture. Integration test with a mock CLI that exercises the verdict parser contract.

### Workflow install steps (Replace)

**Two migration options:**

**Option A (defer to Python):** Remove the `Install opencode` and `Install skills` steps from the workflow entirely. Move setup logic into `_run_agent`: if `agent.setup` is set, run it before the agent. The opencode install becomes a setup script that flow authors must add. **Problem:** breaks existing workflows that rely on automatic opencode install and skills clone.

**Option B (hybrid):** Keep the workflow steps for opencode's automatic install. Add an `agent_setup` field to the `route` workflow output that carries aggregated setup commands. The workflow step iterates unique setup commands, running each. The existing `Install opencode` and `Install skills` steps become conditional: they only run when no `agent.command` is configured (i.e., the default opencode path).

**Recommendation:** Start with Option B for backward compatibility. The workflow step conditionally runs setup commands from the matrix. A future release can migrate to Option A when all flows explicitly declare their setup.

### `AgentStep` fields (Extend)

**Field naming convention in flows.yml:**

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

**Precedence:** Step-level `command` is the only meaningful level (no base/default). `env` merges step-level with any default env map (none by default). `setup` and `verdict_parser` are step-level only.

### Verdict parser `$OUTCOME_YAML` contract (design clarification)

The engine owns the `$OUTCOME_YAML` file for custom commands. The verdict parser does NOT write the file — it only communicates via exit code. The engine maps exit code to verdict:

| Parser exit code | Verdict written to `$OUTCOME_YAML` |
|---|---|
| 0 | `approved` |
| 1 | `changes-requested` |
| 2+ (or any non-zero) | `rejected` |

For the default opencode path, opencode itself writes `$OUTCOME_YAML` as it does today. The engine does not modify or re-parse it.

This design keeps the parser contract minimal (exit code only, no file system side effects) and preserves backward compatibility (opencode's existing `$OUTCOME_YAML` output passes through unmodified).

## Assumptions About Existing Code

- The opencode install (`curl -fsSL https://opencode.ai/install | bash`) creates an `opencode` binary on `PATH` accessible to the `uv run` subprocess. If setup hooks are moved to `_run_agent`, the subprocess inherits the parent's `PATH` (default `subprocess.run` behavior).
- `$OUTCOME_YAML` is always unlinked before each agent run (`run_rule.py:67`). Custom commands with verdict parsers write a fresh file at the same path. The `_execute_rule` caller already handles unlinking, so the custom write is safe.
- No rule currently uses more than one agent step. `split_steps` validation enforces this at the rule level.
- `has_agent` in the Actions matrix output is a single boolean aggregate across all matched rules, not per-rule. This is an existing limitation: if multiple rules with different runtimes match the same event, the current single-install-step approach is insufficient. The hybrid migration addresses this via aggregated `agent_setup`.

## Open Questions

1. How should the workflow install step discover which runtime(s) the matched rules need? The matrix output is a JSON array; add an `agent_setup` field per matrix entry and aggregate unique values in the workflow step. Is this sufficient, or do we need a more structured approach (e.g., a map of runtime -> setup command)?
2. Should `agent.command` accept only a string (shlex-split) or also an explicit list? Accept both: string uses `shlex.split`, list uses as-is. This matches Python subprocess conventions.
3. How should built-in parsers be registered and discovered? Simple match by command basename (e.g., `codex` -> built-in Codex parser). Is this sufficient, or do we need a registry dict mapping command name to parser module?
4. Should the verdict parser receive step metadata (step name, workflow ID, event payload) via environment variables, or is the exit-code-only contract sufficient? Requirements specify stdout-only, so start minimal. Metadata can be added in a later iteration.
5. Can the `--list-runtimes` feature (FR-08) be resolved by scanning built-in parsers + user-defined parser path at startup, or does it need a registration mechanism? Scanning is sufficient for v1.
6. Should sandboxing (NFR-03) use environment restriction (drop `GH_TOKEN`, restrict `PATH`) or container-based isolation (bubblewrap, nsjail)? Environment restriction is the practical first step; container isolation is a hardening option. The parser interface should be designed so container wrapping is a transparent addition later.
7. For `{{prompt_file}}`, should the engine create a temporary file during `_run_agent` (and clean up afterward), or should prompt-kind steps always write the prompt to a known location (e.g., `$RUNNER_TEMP/prompt.md`) before the agent runs? Temp file creation keeps the scope local but requires careful cleanup (handle signal/kill). A known-location approach is simpler but couples the workflow step to the agent step. Temp file with `tempfile.NamedTemporaryFile(delete=False)` + cleanup in a `finally` block is recommended.
8. When `agent.command` contains `{{prompt}}` (inline prompt text), the expanded value may be very large (multi-kilobyte prompt body). Does the target CLI accept the prompt as a command-line argument, or should `{{prompt}}` imply creating a temp file and substituting the path instead? The analysis currently treats `{{prompt}}` as inline text substitution; CLI authors should use `{{prompt_file}}` for large prompts. Document this distinction.
