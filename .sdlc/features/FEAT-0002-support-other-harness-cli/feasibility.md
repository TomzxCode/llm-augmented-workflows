---
issue: "#18"
title: "Support other harness CLI"
status: in-review
---

# Feasibility Assessment: Support Other Harness CLI

## Overview

The engine currently hardcodes `opencode` as the only AI agent runtime for the `agent` step type. Flow authors who need a different CLI (Codex, Gemini CLI, Claude Code, etc.) must fall back to `shell` steps, which bypass the engine's outcome/verdict routing. This feature introduces a configurable `agent.command` setting with pluggable verdict parsers, setup hooks, per-runtime environment variables, template expansion, and distributable parsers so label-driven workflows work regardless of runtime.

## Technical Feasibility

| Criterion | Assessment |
|---|---|
| Required technologies | Available in-house (Python stdlib `subprocess`, `shlex`, `tempfile`, `importlib`) |
| Integration complexity | Medium |
| Technical risks | Template expansion edge cases (escaping, large prompts); subprocess lifecycle management (timeout propagation across agent + parser); sandboxing (NFR-03) without container runtime; cross-platform compatibility of verdict parser subprocess contract |
| Existing components to reuse | `_run_agent` call site (one function to modify), `run_shell` subprocess pattern, `$OUTCOME_YAML` routing in `apply_outcome.py`, `AgentStep` dataclass (extend, not replace), `agent_to_dict` serialization |

The feature requires no new runtime dependencies beyond Python's stdlib (`subprocess`, `shlex`, `tempfile` for template expansion, `importlib` for parser discovery). The existing architecture is well-positioned: `_run_agent` in `run_rule.py:49-56` is the sole call site, `on_outcome` routing is already decoupled from how the agent ran, and the `shell` step type provides a proven subprocess pattern to follow. Template expansion for `{{prompt_file}}` and `{{env.VAR}}` introduces moderate complexity in escaping and temp file lifecycle management. Verdict parser sandboxing (NFR-03) via environment restriction is feasible without container infrastructure; container-based isolation would be a hardening option for v2.

**Verdict:** Feasible

## Financial Feasibility

| Criterion | Assessment |
|---|---|
| Estimated effort | M |
| Infrastructure costs | None (runs on existing GitHub Actions runners or self-hosted runners; no new services) |
| Third-party costs | None (all candidate CLIs are user-installed; no SaaS licenses or API subscriptions required by the engine) |
| ROI expectation | High — removing the opencode lock-in allows flow authors to adopt their preferred or mandated AI CLI without forking the engine, expanding the tool's applicability across teams with different runtime requirements |

The effort is estimated as Medium based on the codebase analysis: the blast radius is small (single call site), but the implementation involves multiple new subsystems (template expansion, verdict parser orchestration, parser discovery, sandbox enforcement, built-in parsers for Codex and Gemini, workflow install step changes). No infrastructure or third-party costs are incurred. The primary cost is development time.

**Verdict:** Feasible

## Operational Feasibility

| Criterion | Assessment |
|---|---|
| Team availability | Partially (single-maintainer project; feature requires focused implementation across engine, workflow, and parser domains) |
| Skill gaps | None significant (Python stdlib subprocess management, YAML config parsing, GitHub Actions YAML — all skills already demonstrated in the codebase) |
| Maintenance burden | Medium — built-in parsers for Codex and Gemini must track CLI output format changes; template expansion adds a surface for edge-case bugs; parser discovery path requires backward-compatible evolution |
| Organizational alignment | Fits roadmap (issue is labeled through analysis-approved and create-feasibility in the pipeline) |

The feature is operationally feasible with conditions. The single-maintainer team must allocate focused time for implementation, testing (unit tests for each subsystem, integration tests with mock CLIs), and documentation of the verdict parser contract. The maintenance burden is Medium because CLI output formats (Codex, Gemini) may change without notice, requiring parser updates. The parser plugin interface must be designed with versioning from day one.

**Verdict:** Feasible with conditions

## Go/No-Go Decision

**Overall verdict:** Go with conditions

**Conditions (if any):**

1. A spike must validate the template expansion design (`{{prompt_file}}` temp file lifecycle, `{{prompt}}` inline substitution for large prompts) before implementation begins.
2. The verdict parser contract must be documented as a stable subprocess interface (stdin-only, exit-code-based) before any parsers are built, with explicit versioning guidance for future format changes.
3. NFR-03 sandboxing must start with environment restriction (dropping `GH_TOKEN`, minimal `PATH`) and defer container isolation to a follow-up; the parser interface should be designed so wrapping is transparent.

## Open Questions

1. Should template expansion support nested placeholders or conditional logic, or remain purely substitutive (flat key-value replacement)?
2. Is the single-aggregate `has_agent` boolean in the Actions matrix output sufficient, or do we need per-rule runtime metadata for the workflow install step?
3. Should the built-in Codex and Gemini parsers ship with the engine or as separate packages, given they may need updates independent of engine releases?
