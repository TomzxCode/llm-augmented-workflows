---
artifact: codebase-analysis
verdict: approved
reviewed_at: 2026-06-28
---

## Coverage

One minor gap remains from the previous review:

- **NFR-03 (5-second dispatch budget):** The requirement is mentioned briefly in the `run_steps.py` constraint section ("Retry delays (1s, 2s, 4s) must not exceed NFR-03") but no component's latency characteristics are systematically mapped against the 5-second budget. This was noted as Low in the prior review and remains unaddressed. Consider adding a brief note on which operations contribute to dispatch latency and why the budget is feasible.

All `Must` and `Should` requirements (FR-01 through FR-08) are now covered. FR-09 and FR-10 (`May` priority) are acknowledged but not analyzed in depth, which is acceptable given their priority.

Search entry points are recorded (lines 20-25) and the scope is clearly delineated with explicit out-of-scope items.

## Accuracy

No issues found. Every component path, line count, responsibility description, and behavior claim was verified against the actual source:

- All 7 source file line counts verified (engine.py=449, route.py=96, run_rule.py=169, run_steps.py=117, apply_outcome.py=108, cli.py=47, sync_labels.py=50)
- dispatch.yml line count verified (177)
- Env variable reads in route.py, run_rule.py, run_steps.py, apply_outcome.py verified against source
- `matches()` function check matrix (event, action, label, merged, branch_prefix, body_contains) verified at engine.py:320-345
- `find_next_rules()` scope (issues event + labeled action only) verified at engine.py:89-113
- `split_steps()` one-agent constraint verified at engine.py:194-231
- Test coverage claim (510 lines) verified against tests/test_engine.py
- `_gh()` retry-less `subprocess.run` with `check=True` confirmed at run_steps.py:24-31
- Parameterless `_current_subject()` reading `ISSUE_NUMBER`/`PR_NUMBER` from env confirmed at run_steps.py:34-41
- `cli.py` subcommand dispatch pattern confirmed at cli.py:37-42

## Changeability Rigor

No issues found. Every component has exactly one disposition:

| Component | Disposition | Risk | Constraints stated |
|---|---|---|---|
| engine.py | Reuse as-is | Low | Yes |
| route.py | Extend | Low | Yes (behavioral identity) |
| run_rule.py | Refactor | Medium | Yes (behavioral identity) |
| run_steps.py | Refactor | Medium | Yes (NFR-03 constraint noted) |
| apply_outcome.py | Refactor | Low | Yes |
| cli.py | Reuse as-is | None | Yes |
| sync_labels.py | Reuse as-is | None | Yes |
| dispatch.yml | Keep as-is | None | Yes |
| Server (greenfield) | Create new | Not assessed | N/A |

Each disposition is justified with a rationale tied to the coupling map and requirements. Risk levels are concrete and the risk drivers are explicit (e.g., "the continuous mode loop is non-trivial" for run_rule.py; "retry logic must not mask genuine failures" for run_steps.py).

Constraints include behavioral identity requirements for route.py and run_rule.py — the refactored functions must produce identical outcomes for the same input.

## Impact and Migration

No issues found. Prior concerns from the previous review are resolved:

- **FR-07 (graceful shutdown):** Addressed in lines 243-251 with concrete signal handling, in-flight tracking via `asyncio.Event`, drain behavior, and at-most-once semantics.
- **NFR-06 (retry with exponential backoff):** Addressed in lines 237-241 with explicit 3-attempt strategy, backoff delays, error classification, and exhaustion behavior.
- **Env var racing:** Resolved via parameter injection with env var fallback (lines 259-265), with a clear statement that `os.environ` is never written by the server path.
- **dispatch.yml disposition:** Corrected to "Keep as-is" (line 161).

The migration sections for each refactored component (route.py, run_rule.py, run_steps.py, apply_outcome.py) provide concrete extraction steps, backward compatibility strategy, and de-risking measures.

The greenfield server components have adequate implementation detail covering the Docker image, SQLite schema/crash recovery, retry logic, graceful shutdown, and structured logging.

## Coupling Awareness

No issues found. The dependency and coupling map (lines 46-96) is thorough and accurate:

- Environment variable coupling correctly identified as the primary coupling to the Actions environment, with each env var enumerated (lines 67-71)
- gh CLI coupling correctly assessed as tight (lines 73-76)
- opencode CLI subprocess dependency identified (lines 78-80)
- SQLite dependency correctly noted as having no coupling to existing code (lines 82-84)
- Docker image dependencies enumerated (lines 86-88)
- Blast radius for each module is correctly assessed (lines 90-97)

The coupling-aware changeability assessment in each component section accounts for downstream effects — for example, run_rule.py notes that modifying orchestration logic affects both execution paths, and the refactoring plan calls for backward-compatible signatures throughout.
