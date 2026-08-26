---
issue: "#17"
status: Active
---

# Assumption: Anti-spoofing (NFR-05) can be implemented without modifying the flow engine

**Date:** 2026-06-28
**Status:** Active
**Author:** Specification review

---

## Statement

The NFR-05 requirement that the express flow rule verify the label origin (ensuring `llmaw:express-eligible` was applied by automation, not by a human or compromised actor) can be implemented without changes to the engine's core matching logic (`engine.py`, `route.py`).

## Basis

The specification claims "zero engine changes" in the Technical Decisions table. The anti-spoofing mechanism is described using "e.g." phrasing suggesting two candidate approaches (timeline verification, same-workflow-run check), neither of which is specified in detail.

## Confidence

**Level:** Low

The engine's `matches()` function (`engine.py:233-258`) has no concept of label origin. The `When` dataclass only supports matching on label name. Implementing origin verification would require either: (a) extending `When` with an `origin` field, (b) adding deterministic pre-steps that check label history via `gh`, or (c) using a separate label (set only by automation) as the sole trigger. Options (b) and (c) might work without engine changes, but the spec does not specify which approach is used.

## Risk if Wrong

**Impact:** High

If no mechanism exists to prevent a human from manually applying `llmaw:express-eligible` to a complex feature, NFR-05 is violated. A compromised token could bypass planning on any feature. The express flow rule would match the label regardless of origin, routing complex features through the express path without planning artifacts.

## Validation Plan

**Method:** Prototype the anti-spoofing check against actual GitHub events to confirm the chosen mechanism (timeline API call or deterministic pre-step) works without engine modifications.
**Owner:** Implementation team
**By:** Before shipping the express path to production

## Related

- Specification: Anti-spoofing section (line 90), Technical Decisions (line 323)
- NFR-05 in requirements
