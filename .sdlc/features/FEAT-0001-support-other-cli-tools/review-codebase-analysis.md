---
artifact: codebase-analysis
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Coverage

1. **FR-06 not addressed** — Requirement FR-06 (validate configured `agent.command` exists and is executable before running the agent step, with a clear error message if not) has no corresponding component disposition. The `_run_agent` Replace section does not mention pre-execution command validation.

2. **FR-09 not addressed** — Requirement FR-09 (distributable parsers loaded from a configurable `parsers.path` directory, default `~/.config/opencode/parsers/`) is not addressed. The analysis covers a `parsers/` submodule for built-in parsers but does not account for user-installed parsers discovered at runtime.

3. **NFR-03 not addressed** — Requirement NFR-03 (custom verdict parsers run in a sandboxed subprocess with no network access unless explicitly configured) is not mentioned in any component disposition.

4. **NFR-04 partially addressed** — The analysis mentions "stderr capture" and logging under `_run_agent` risk but does not explicitly address the requirement to log the configured agent command at DEBUG level before execution and the exit code at DEBUG level after execution.

5. **NFR-01 partially addressed** — The analysis mentions "timeout propagation" in `_run_agent` risk but does not explicitly address the 30s default timeout for verdict parsers specifically.

## Accuracy

1. **Workflow files do not exist in the repository** — The analysis lists `.github/workflows/dispatch.yml` and `.github/wrappers/dispatch.yml` as entry points (line 21) and identifies `Install opencode workflow step` at `.github/workflows/dispatch.yml:129-141` as a component with a `Replace` disposition. Neither file exists in the current repository. Claims about the workflow step's behavior (unconditional opencode install, `has_agent` boolean aggregation) cannot be verified against the codebase. The migration analysis for this component (two options, Option B recommendation) is based on assumptions about a file that does not exist.

## Changeability Rigor

1. **Contradictory constraints for `_run_agent`** — The constraint "Must support both string commands (shell-cmded via `shell=True`) and list commands" (line 116) conflicts with "Must NOT use `shell=True` by default (security constraint from existing code style)" (line 117). Without `shell=True`, `subprocess.run` does not accept string arguments. Shlex-splitting strings resolves this, but the parenthetical "(shell-cmded via `shell=True`)" implies a different execution model. Clarify whether string commands are shlex-split (recommended, secures the default) or passed with `shell=True` (riskier, opt-in only).

## Impact and Migration

1. **Verdict parser `$OUTCOME_YAML` contract ambiguity** — The analysis asserts "the parser writes `$OUTCOME_YAML` with the verdict" (line 132), implying the parser subprocess writes the YAML file. However, the requirements constraint states "Verdict parsers communicate their result via exit code" (requirements.md line 51), meaning the exit code is the contract. It is unclear whether (a) the parser writes `$OUTCOME_YAML` itself and the engine reads it after, (b) the engine maps the parser's exit code to `$OUTCOME_YAML` internally, or (c) both. This design ambiguity affects the parser interface contract, backward compatibility (opencode already writes `$OUTCOME_YAML`), and the `on_outcome` pipeline stage. Resolve and document.

## Coupling Awareness

No issues found.
