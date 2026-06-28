---
issue: "#17"
status: Active
---

# Assumption: create-implementation skill works from issue body and labels only

**Date:** 2026-06-28
**Status:** Active
**Author:** Specification review

---

## Statement

The `create-implementation` skill can produce working code and tests from only the issue body and labels, without requiring requirements, specifications, codebase-analysis, or other planning-phase artifacts as input.

## Basis

The spec treats `create-implementation` as a black box and lists its modification as "Out of Scope." No code review or testing has been done to verify this assumption. The feasibility review identified this as the central risk of the express path.

## Confidence

**Level:** Low

No evidence that `create-implementation` currently tolerates missing planning artifacts. If it imports or reads these artifacts during initialization, it will crash or produce low-quality output.

## Risk if Wrong

**Impact:** High

The entire express path is blocked. Every express-path run would fail with an error from `create-implementation`, rendering the feature non-functional until `create-implementation` is modified to accept a reduced input set.

## Validation Plan

**Method:** Run `create-implementation` against a simulated "issue body + labels only" input (bypassing the full artifact chain) in a test environment.
**Owner:** Implementation team
**By:** Before shipping the express path to production

## Related

- Specification: Risks section (line 337), Out of Scope (line 357)
