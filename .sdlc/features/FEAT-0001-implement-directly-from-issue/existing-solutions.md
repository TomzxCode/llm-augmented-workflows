---
issue: "#17"
title: "Implement directly from issue"
status: in-review
---

# Existing Solutions: Implement directly from issue

## Overview

The feature requires an express path from issue classification to implementation PR, skipping the planning phases (requirements, existing-solutions, codebase-analysis, feasibility, specifications, telemetry, observability, plan, tasks) for well-understood, low-complexity features. The survey found no off-the-shelf system that combines a complexity classifier with a workflow router to skip planning phases while producing a minimal artifact trail. However, several systems provide strong prior art: Elastic's `gh-aw-issue-fixer` implements a conditional fast-path decision, `gha-issue-triage` emits complexity scores usable for routing, and the project's own bugfix pipeline provides an architectural template for how a fast path works within the existing flows framework. The recommended direction is **build** — add an express-pipeline flow to `flows.yml` that routes toward `create-implementation` when triage classifies an issue as low-complexity — with patterns borrowed from the evaluated systems for classification heuristics and artifact-light traceability.

## Search Scope

| Source | Searched | Notes |
|---|---|---|
| Internal codebase | Yes | Full feature pipeline (`flows.yml:198-475`), bugfix fast path (`flows.yml:476-521`), triage flow (`flows.yml:183-196`), engine code (`engine.py`, `route.py`, `run_rule.py`) |
| Open-source | Yes | GitHub Actions-based issue-to-PR bots (Sweep AI, AutoPR, gen-pr, DAIV), LLM triage classifiers (gha-issue-triage, n8n-github-triage-demo, RepoRouter), multi-agent pipeline frameworks (nowline/lolay, claude-swe-workflows) |
| Commercial / SaaS | Yes | GitHub Agentic Workflows (`gh-aw`), GitHub Copilot Coding Agent, Sweep.dev |
| Standards / protocols | Yes | BPMN 2.0 agentic workflow patterns (branching gateway, escalation, linear handoff) |
| Reference material | Yes | CI/CD fast-path lane segmentation patterns, academic benchmarks on LLM issue classification (80%+ F1), LangChain fast-path semantic router proposals |

## Candidate Solutions

| Solution | Type | License | Maturity | Covers | Gaps |
|---|---|---|---|---|---|
| **Project's bugfix fast path** (`flows.yml:476-521`) | Internal | MIT | Production | FR-01 (label-driven routing), FR-04 (parallel path co-existence), FR-06 (label overrides), NFR-04 (orthogonality) | No complexity classification (bug vs feature is hardcoded), no configurable criteria (FR-01), no metrics (FR-07), no artifact trail (FR-03) |
| **Elastic `gh-aw-issue-fixer`** | Open-source | Elastic-2.0 | Production | FR-01 (conditional routing: "small, clear, verifiable -> implement directly"), FR-02 (skip planning for simple fixes) | No artifact trail (FR-03), no configurable criteria (FR-01 NFR-03), no metrics (FR-07), GitHub Agentic Workflows only (not portable) |
| **`qte77/gha-issue-triage`** | Open-source | MIT | Active | FR-01 (complexity: low/medium/high + feasibility), FR-05 (classification logging) | Focused on triage output only, no workflow routing or implementation (FR-02, FR-03, FR-04) |
| **`n8n-github-triage-demo`** | Open-source | Not specified | Demo | FR-01 (complexity: good-first-issue / regular / complex), FR-05 (logging) | Proof-of-concept only, no implementation path (FR-02, FR-03, FR-07) |
| **`pattern-stack/claudecode-patterns`** | Open-source | Not specified | Active | FR-01 (`gate:auto` label bypasses human approval), FR-06 (label-based override) | Claude Code-specific, no artifact trail (FR-03), no complexity classifier built-in |
| **`WillBooster/gen-pr`** | Open-source | MIT | Active | FR-02 (optional `--planning-model` to skip planning), NFR-01 (configurable pipeline depth) | No classification (FR-01), no artifact trail (FR-03), CLI tool not event-driven |
| **GitHub Agentic Workflows** | Commercial/SaaS | Proprietary | Public preview | FR-01 (`assignees: copilot` skip-plan shortcut), NFR-03 (Markdown-defined config) | GitHub-only lock-in, no complexity classifier (relies on manual assignment), no metrics (FR-07) |
| **GitHub Copilot Coding Agent** | Commercial/SaaS | Proprietary | Public preview | FR-02 (implements assigned issues directly, opens PR), FR-04 (parallel to other workflows) | No complexity classification, no configurable criteria (FR-01 NFR-03), no artifact trail (FR-03), lock-in |
| **nowline/lolay agent-triage state machine** | Open-source | Not specified | Active | FR-01 (three-way plan-phase routing), FR-06 (human override points), different models per phase depth | No complexity classifier for express eligibility, complex state machine may conflict with existing flows pattern |
| **BPMN 2.0 branching gateway pattern** | Standard | N/A | Stable | FR-01 (classification gates routing), FR-04 (parallel lanes) | Abstract pattern, no implementation, no artifact trail or metrics |
| **CI/CD fast-path lane segmentation** | Reference | N/A | Stable | NFR-01 (separate fast path from full validation), NFR-04 (orthogonal lanes) | General pattern only, no implementation for issue-to-code pipelines |

## Evaluation

### Project's bugfix fast path (internal)

- **Strengths:** Already integrated into the flows framework, proven label-driven state machine pattern, established branching (`fix/`, `sdlc/issue-N`), uses `on_outcome` verdicts for routing, supports human override via labels.
- **Weaknesses:** No complexity classification (hardcoded to bugs only), produces no artifact trail describing the fast-path decision, no metrics.
- **Integration effort:** Low — the feature's express path would mirror the bugfix flow structure, adding a new `express` flow alongside `bugfix` and `feature`.
- **Cost:** Zero (internal code).
- **Risks:** Low — pattern already proven in production.
- **Forward compatibility:** The flows framework is under active development by the same team; the express path would evolve with it naturally.

### gha-issue-triage

- **Strengths:** Directly emits `complexity` (low/medium/high) and `feasibility` (yes/no) — the exact signals needed for express-path classification. MIT license. Active development, well-documented, works as a GitHub Action.
- **Weaknesses:** Output-only — does not route or implement. Would need integration into the existing flows pipeline. Requires an additional API call per issue.
- **Integration effort:** Medium — would either call gha-issue-triage as a step in the triage flow, or replicate its classification logic into the existing `triage-issue` skill.
- **Cost:** Free (MIT). No infrastructure cost.
- **Risks:** Low — the classification signal is a structured output we consume, not a dependency we take on. If gha-issue-triage becomes unmaintained, we can replicate the logic or swap the classifier.
- **Forward compatibility:** Dependency is minimal (structured JSON output); we can replace the classifier without changing the routing.

### Elastic gh-aw-issue-fixer

- **Strengths:** Closest match to the express-path concept — a single agentic workflow that decides "implement directly" vs "analyze only" based on fix complexity. Production-proven at Elastic.
- **Weaknesses:** Tightly coupled to GitHub Agentic Workflows (`gh-aw`), which is proprietary and GitHub-only. Uses a different workflow model than this project's `flows.yml` + engine approach.
- **Integration effort:** High — would require porting the pattern from gh-aw to the existing flows framework, or adopting gh-aw wholesale (which would conflict with the existing engine).
- **Cost:** Free (public preview). No direct licensing cost, but migration to gh-aw would be expensive.
- **Risks:** Lock-in to GitHub's proprietary agentic workflow system. The project's engine is portable across any GitHub Actions runner; gh-aw is GitHub-only.
- **Forward compatibility:** Not applicable — not adopting.

### pattern-stack/claudecode-patterns

- **Strengths:** Demonstrates `gate:auto` label as a bypass mechanism — the exact pattern for NFR-03 (configurable without code changes) and FR-06 (human override). Well-architected with worktree isolation.
- **Weaknesses:** Claude Code-specific, tightly coupled to its CLI interface. No built-in complexity classification — relies on manual label application.
- **Integration effort:** Medium — the `gate:auto` concept is worth borrowing but the implementation is not reusable.
- **Cost:** Free. No licensing cost.
- **Risks:** Low (pattern only, not a dependency).
- **Forward compatibility:** Not a dependency — pattern borrowing only.

### WillBooster/gen-pr

- **Strengths:** Optional `--planning-model` flag directly implements the "skip planning" concept (FR-02). Configurable via YAML (NFR-03). Multiple AI backend support.
- **Weaknesses:** CLI tool, not event-driven. No issue classification (FR-01). No artifact trail (FR-03). No metrics (FR-07). Would require a wrapper to integrate into flows.yml.
- **Integration effort:** Medium — would wrap in a shell step, but loses the event-driven label state machine pattern.
- **Cost:** Free (MIT).
- **Risks:** Low — single-purpose tool, can be replaced.
- **Forward compatibility:** Not adopting as a dependency, but worth noting the `--planning-model` flag design.

## Recommendation

**Direction:** Build

**Rationale:**

No existing system combines complexity classification with configurable pipeline routing and artifact-light traceability in a portable, event-driven, label-state-machine architecture. However, strong prior art exists for each component:

1. **Classification** (FR-01, FR-05): Borrow `gha-issue-triage`'s complexity scoring approach and `n8n-github-triage-demo`'s three-tier model (`good-first-issue` / `regular` / `complex`). Replicate the classification logic inside the existing `triage-issue` skill rather than introducing a new dependency. The triage agent already classifies issues as `feature` vs `bug`; extending it with a complexity dimension is the natural evolution.

2. **Routing** (FR-02, FR-04, FR-06): Mirror the bugfix fast path (`flows.yml:476-521`). Add an `express` flow with rules that route directly to `create-implementation` when the triage verdict includes `complexity: low` (or a human-applied `llmaw:quick-implement` label overrides the classification). The existing `on_outcome` verdict system handles routing naturally.

3. **Artifact trail** (FR-03): Borrow the nowline/lolay approach of a lightweight "route decision" comment or label rather than a full `.sdlc/` artifact per fast-path feature. A single `llmaw:express-path` label plus a comment recording the classification rationale satisfies traceability without the overhead of a multi-phase artifact chain.

4. **Configuration** (NFR-03): Define the express-path criteria in `flows.yml` alongside the existing `defaults:` block, following the same configuration pattern already used for models and timeouts. This keeps configurability code-change-free.

5. **Metrics** (FR-07): The project's existing setup (no dashboard) suggests a lightweight approach: record express-path usage as issue comments or labels, which can be queried via `gh issue list --label llmaw:express-path`. A periodic aggregation step or manual query suffices until usage warrants a dashboard.

## Sources of Information

- **Bugfix fast path** (`flows.yml:476-521`): Label-driven state machine pattern, `on_outcome` verdict routing, parallel path co-existence without conflicts.
- **Elastic gh-aw-issue-fixer**: Conditional fast-path decision pattern — the "implement directly vs. analyze only" gate is the core concept.
- **gha-issue-triage**: Complexity classification output schema (low/medium/high) and the pattern of adding it to triage without introducing a new API dependency.
- **pattern-stack/claudecode-patterns**: `gate:auto` label as a bypass mechanism — an elegant, label-driven override that requires zero code changes.
- **CI/CD fast-path lane segmentation**: Three-tier model (fast path / protected / deferred) that validates the orthogonal-lane architecture in NFR-04.
- **Academic LLM classification benchmarks**: Validates that LLM-based complexity classification (80%+ F1) is sufficient for routing decisions.
- **n8n-github-triage-demo**: Three-tier complexity schema (good-first-issue / regular / complex) as a concrete default for FR-01 classification criteria.

## Open Questions

1. Should the express-path eligibility be decided at triage time (extending the `triage-issue` skill's verdict) or as a separate routing step after triage? The first is more efficient (single pass); the second is more modular.
2. What is the default three-tier complexity criteria? (Issue body length? Change scope estimate? Label presence? A combination?) The requirements specify configurable criteria but do not define defaults for the initial implementation.
3. Should the express path produce a `llmaw:express-path` artifact label on the issue (traceable via label queries for metrics) or a lightweight `.sdlc/features/*/express-decision.md` file? Labels are cheaper but less durable; artifacts are more robust but cost tokens.
4. Should the express path default to a human-applied label (e.g., `llmaw:quick-implement`) or should the triage agent classify automatically and emit the label? FR-06 supports human override regardless, but the default mode affects DX.
5. How should the express path handle the initial issue triage record? Currently every new issue goes through `triage-new-issue`. The express path would need to either (a) consume the triage verdict as-is, (b) add a new triage class (`express-feature`), or (c) re-classify after triage. Option (b) extends the existing verdict vocabulary with minimal change.
