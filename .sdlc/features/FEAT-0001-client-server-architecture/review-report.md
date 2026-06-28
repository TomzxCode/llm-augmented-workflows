# Review Report: Codebase Analysis

## Coverage

| Finding | Severity | Details |
|---|---|---|
| FR-07 (graceful shutdown) not addressed | Medium | The requirement "finish in-flight agent executions before terminating" is not mapped to any analyzed component. Graceful shutdown implies changes to the server's lifecycle (SIGTERM handling, connection draining, in-flight tracking) that are not analyzed. |
| FR-08 (structured logging) not addressed | Low | The requirement for structured logging of all webhook events, agent decisions, and outbound API calls is not covered. The existing code uses `logging.basicConfig` with plain-text format; the analysis does not identify what needs to change. |
| NFR-03 (5-second processing) not addressed | Low | The performance requirement for processing within 5 seconds (excluding LLM time) is not analyzed against any component's latency characteristics. |
| NFR-06 (retry with exponential backoff) not addressed | Medium | The requirements specify up to 3 retries with exponential backoff on GitHub API errors (FR-05 acceptance criterion). `run_steps.py` and `apply_outcome.py` are marked "Reuse as-is" but would need retry logic to satisfy this requirement. |
| Constraint "must not require changes to downstream repos" not addressed | Low | The constraint that agent behavior must be identical from the user's perspective (no changes to how repos write issue/PR descriptions) is not explicitly verified against the refactoring plan. |

## Accuracy

No issues found. Every component path, line count, responsibility description, and behavior claim was verified against the actual source:

- All 7 source file line counts verified (engine.py=449, route.py=96, run_rule.py=169, run_steps.py=117, apply_outcome.py=108, cli.py=47, sync_labels.py=50)
- dispatch.yml line count verified (177)
- Env variable reads in route.py, run_rule.py, run_steps.py, apply_outcome.py verified against source
- `matches()` function check matrix (event, action, label, merged, branch_prefix, body_contains) verified at engine.py:320-345
- `find_next_rules()` scope (issues event + labeled action only) verified at engine.py:89-113
- `split_steps()` one-agent constraint verified at engine.py:220-228
- Test coverage claim (510 lines) verified against tests/test_engine.py

## Changeability Rigor

| Finding | Severity | Details |
|---|---|---|
| dispatch.yml disposition "Replace" is misleading since the file is not modified | Low | The analysis assigns "Replace" to dispatch.yml but explicitly says it "stays for repos that do not migrate" and is "not modified." The disposition should be "Keep as-is" for non-migrated repos, with the server model being a new (greenfield) path. The current framing implies a change that does not exist. |
| Missing explicit constraint on behavioral identity | Low | The refactored route.py and run_rule.py must preserve the exact same agent behavior visible to downstream users (same comments, labels, outcomes). This constraint from the requirements is not stated in the analysis's constraint sections for those components. |

## Impact and Migration

| Finding | Severity | Details |
|---|---|---|
| Env var racing for concurrent multi-repo is identified but unresolved | Medium | Open Question 1 identifies that concurrent requests could race on shared env vars (`GH_TOKEN`, `ISSUE_NUMBER`, `PR_NUMBER`). The analysis suggests `run_in_executor` per-repo as a workaround but provides no concrete migration plan or de-risking measure (e.g., thread-local storage, passing parameters instead of env vars). This is a blocking concern for multi-repo support (NFR-04). |
| Retry logic for gh CLI failures not addressed | Medium | Moving `gh` CLI calls from GitHub Actions (which has built-in retry behavior) to a server environment removes the implicit retry. The analysis does not plan for adding retry with exponential backoff to `run_steps._gh()` or `apply_outcome._post_comment()` / `_close()` to meet NFR-06. |

## Coupling Awareness

No issues found. The dependency and coupling map (lines 46-96) is thorough and accurate:

- Environment variable coupling correctly identified as the primary coupling to the Actions environment
- gh CLI coupling correctly assessed as tight
- opencode CLI subprocess dependency identified
- New SQLite dependency correctly noted as having no coupling to existing code
- Docker image dependencies enumerated
- Blast radius for each module is correctly assessed

## Overall Verdict

**changes-requested** — The analysis is well-researched and accurate in its component descriptions, but has gaps in requirement coverage (FR-07, FR-08, NFR-03, NFR-06) and the env var racing concern for concurrent multi-repo execution needs a concrete resolution plan before it can proceed.

### Required fixes before approval

1. Address FR-07 (graceful shutdown) by analyzing what server lifecycle changes are needed (SIGTERM handler, in-flight tracking, drain timeout).
2. Address NFR-06 / FR-05 retry requirement by analyzing changes needed to `run_steps.py` and possibly `apply_outcome.py` for exponential backoff on gh CLI failures.
3. Resolve the env var racing concern (Open Question 1) with a concrete approach (thread-local storage, passing parameters instead of env vars, or explicitly limiting to single-threaded per-repo execution).
4. Clarify dispatch.yml disposition ("keep as-is" rather than "replace").

### Recommended before approval

5. Map FR-08 (structured logging) to the affected components.
6. Add the behavioral-identity constraint to the refactored component constraint sections.
