---
issue: "#18"
title: "Support other harness CLI"
status: approved
---

# Requirements: Support Other Harness CLI

## Overview

The engine currently hardcodes `opencode` as the only AI agent runtime for the `agent` step type. Flow authors who need to use a different CLI (Codex, Gemini CLI, Claude Code, etc.) must fall back to `shell` steps, which bypass the engine's outcome/verdict routing. This feature allows the agent step to be configured to use any supported CLI, with a pluggable verdict parser so that label-driven workflows work regardless of runtime.

## Stakeholders

| Stakeholder | Interest |
|---|---|
| Flow authors / workflow consumers | Want to select their preferred AI CLI without losing verdict integration |
| Project maintainers | Need a clean extension point that does not couple the engine to any single runtime |
| Security / compliance admins | Need to mandate a specific approved AI tool and have the engine comply |
| Ops / infrastructure admins | Need to manage installation, auth, and sandboxing per runtime |

## Functional Requirements

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | Must | The system shall support a configurable `agent.command` setting that specifies the CLI executable or full command template for the agent step. |
| FR-02 | Must | The system shall include a built-in verdict parser for `opencode` that preserves current behavior. |
| FR-03 | Must | The system shall allow flow authors to provide a custom verdict parser script or binary that reads agent stdout and exits with a verdict-compatible status. |
| FR-04 | Must | The system shall provide a pre-install hook per runtime (e.g., `agent.setup` script) that runs before the agent step to install or verify the CLI. |
| FR-05 | Should | The system shall include built-in verdict parsers for Codex CLI and Gemini CLI, documented with their supported output formats. |
| FR-06 | Should | The system shall validate the configured `agent.command` exists and is executable before running the agent step, with a clear error message if not. |
| FR-07 | Should | The system shall support runtime-specific environment variables (e.g., API keys, model selection) mapped from a configurable `agent.env` map in step configuration, where each key-value pair is set as an environment variable in the agent subprocess. |
| FR-08 | May | The system shall include a `--list-runtimes` flag on the engine CLI that shows registered CLIs and their parser status. |
| FR-09 | May | The system shall allow verdict parsers to be distributed as separate packages or loaded from a configurable `parsers.path` directory (default `~/.config/opencode/parsers/`). |

## Non-Functional Requirements

| ID | Requirement | Category |
|---|---|---|
| NFR-01 | The system shall execute verdict parsers within a timeout configurable per step (default 30s). | Performance |
| NFR-02 | The system shall not regress the existing opencode agent step behavior when `agent.command` is unset or set to the default. | Compatibility |
| NFR-03 | Custom verdict parsers shall run in a sandboxed subprocess with no network access unless explicitly configured. | Security |
| NFR-04 | The system shall log the configured agent command and its exit code at DEBUG level before and after execution. | Observability |

## Constraints

- Backward compatibility: existing workflows that omit `agent.command` must behave identically to today (i.e., invoke opencode with default parsing).
- No changes to the `shell` step type; it continues to exist as an alternative.
- Verdict parsers must not require root or elevated privileges.
- The engine must not ship proprietary or licensed CLIs; users install their chosen runtime independently.
- Verdict convention: verdict parsers communicate their result via exit code — exit 0 = `approved`, exit 1 = `changes-requested`, exit 2+ (or non-zero) = `rejected` / error. This convention applies to built-in parsers and is the minimum contract for custom parsers.

## Acceptance Criteria

- [ ] **FR-01** (happy path)
    - **Given** a workflow with `agent.command` set to `"codex"` and `prompt: "summarize this issue"`
    - **When** the agent step runs
    - **Then** the engine invokes `codex` instead of `opencode` with the configured prompt
- [ ] **FR-01** (template expansion)
    - **Given** a workflow with `agent.command: "claude -f {{prompt_file}}"` and a prompt file path
    - **When** the agent step runs
    - **Then** the template is expanded and the command is invoked with the resolved arguments
- [ ] **FR-02** (default behavior preserved)
    - **Given** a workflow with no `agent.command` configured
    - **When** the agent step runs
    - **Then** the engine invokes `opencode` and routes on its exit code exactly as today
- [ ] **FR-03** (custom parser)
    - **Given** a workflow with `agent.verdict_parser: "/usr/local/bin/my-parser"`
    - **When** the agent step completes with stdout "APPROVED"
    - **Then** the engine runs `my-parser` on the agent's stdout and maps its exit code to the verdict
- [ ] **FR-04** (setup hook)
    - **Given** a workflow with `agent.setup: "pip install codex-cli"` and `agent.command: "codex"`
    - **When** the agent step runs
    - **Then** the setup command runs before `codex` and the engine proceeds only if setup exits 0
- [ ] **FR-05** (built-in parser for Codex)
    - **Given** a workflow with `agent.command: "codex"` and no explicit `verdict_parser`
    - **When** the agent step completes
    - **Then** the engine applies the built-in Codex parser to determine the verdict
- [ ] **FR-06** (missing executable)
    - **Given** a workflow with `agent.command: "nonexistent-cli"`
    - **When** the agent step runs
    - **Then** the engine fails fast with a clear error message indicating the command was not found
- [ ] **FR-01** (error)
    - **Given** a workflow with a configured `agent.command`
    - **When** the agent process exits with a non-zero code
    - **Then** the engine captures the exit code and stderr and surfaces them in the step logs
- [ ] **NFR-01** (timeout)
    - **Given** a workflow with `agent.command` set to a CLI that hangs
    - **When** the agent step runs past the configured timeout
    - **Then** the engine kills the subprocess and reports a timeout error
- [ ] **FR-07** (env vars)
    - **Given** a workflow with `agent.command: "codex"` and `agent.env: { API_KEY: "sk-xxx", MODEL: "claude-3-5" }`
    - **When** the agent step runs
    - **Then** the `API_KEY` and `MODEL` environment variables are set in the agent subprocess
- [ ] **FR-08** (list runtimes)
    - **Given** the engine CLI
    - **When** the user runs `engine --list-runtimes`
    - **Then** the output lists each registered runtime with its parser status (built-in, custom, or none)
- [ ] **FR-09** (distributable parser)
    - **Given** a parser script placed at `~/.config/opencode/parsers/codex-parser`
    - **When** `agent.command: "codex"` is used with no explicit `verdict_parser`
    - **Then** the engine discovers and loads the parser from the default parsers path
- [ ] **NFR-02** (no regression)
    - **Given** an existing workflow with no `agent.command` and no `agent.verdict_parser`
    - **When** the agent step runs
    - **Then** the output, exit codes, and verdict routing match the pre-feature behavior exactly
- [ ] **NFR-04** (logging)
    - **Given** a workflow with `agent.command: "codex"`
    - **When** the agent step runs
    - **Then** the engine logs the configured command at DEBUG before execution and the exit code at DEBUG after execution
- [ ] **NFR-03** (sandbox)
    - **Given** a workflow with a custom `agent.verdict_parser` that attempts network access
    - **When** the verdict parser runs
    - **Then** the network call is blocked and the parser fails with a sandbox violation error

## Conflicts

<!-- Populated by /review-requirements. Leave as "None identified yet." when drafting. -->

None identified yet.

## Open Questions

1. Should verdict parsers be standalone executables or could they be inline scripts (e.g., a regex or exit-code mapping in YAML config)? A simpler config-based parser (map exit codes to verdicts) may cover most use cases without requiring users to write scripts.
2. What is the minimum supported interface for a verdict parser — does it receive stdin only, or also env vars with step metadata?
3. How should the engine discover built-in parsers for runtimes that are not installed at engine start (e.g., a parser registered by a third-party package)?
4. What is the upgrade/migration path for existing workflows that use `shell:` to simulate agent steps today?
5. Should the engine support an admin-enforced allowlist of approved `agent.command` values to satisfy the security/compliance stakeholder requirement to "mandate a specific approved AI tool"?
6. Should per-runtime sandbox configuration be supported (e.g., some runtimes need network access, others do not), or is the single global NFR-03 setting sufficient?
