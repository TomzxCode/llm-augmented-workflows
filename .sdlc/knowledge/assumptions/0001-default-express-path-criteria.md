---
issue: "#17"
status: Active
---

# Assumption: Default express path classification criteria can be defined by label presence and issue characteristics

**Date:** 2026-06-28
**Status:** Active
**Author:** Review agent

---

## Statement

The default classification criteria for the express path (label presence and issue body characteristics such as scope clarity) will correctly identify features that can be implemented without full pipeline planning.

## Basis

The project already implements a bug fix fast path that uses label-based routing, proving the pattern is viable. FR-01 makes criteria configurable, so defaults can evolve without code changes. The needs assessment was approved with Moderate evidence.

## Confidence

**Level:** Medium

The criteria defaults have not been tested against real feature data. Usage data (open question 5 in questions.md) would help validate, but the criteria are designed to be configurable.

## Risk if Wrong

**Impact:** Medium

If defaults are too permissive, complex features skip planning and may produce low-quality implementations or violate constraints. If defaults are too restrictive, the express path adds no value and simple features still traverse the full pipeline.

## Validation Plan

**Method:** After the express path is implemented, evaluate the first 10 features processed through it. For each, assess whether the classification was correct (did the feature truly qualify as simple?) and whether the implementation met quality standards.

**Owner:** Project owner (tomzx)

**By:** After the first 10 express-path features have been processed

## Related

- FR-01 (configurable classification criteria)
- FR-06 (human override)
- questions.md question 1 (default criteria)
- issues.md question 5 (usage data)
