# Feasibility Review: Implement directly from issue

## Completeness

No issues found.

All three dimensions (technical, financial, operational) are assessed. Assessment criteria are filled. Open questions are documented (5 in the assessment, plus additional ones captured below).

## Risk Coverage

1. **Unstated assumptions need formal recording.** The assessment implicitly assumes: (a) the flows engine can be extended with new express-flow rules without refactoring existing flow matching logic, (b) the triage-issue skill extension can be shipped in the same release window as the flow config, and (c) the express path pattern mirrors the bugfix fast path cleanly without unforeseen interactions. These should be recorded as assumptions via `/create-assumption`.

2. **Dependency risk is underplayed.** The triage-issue skill lives in an external repo. A coordinated rollout is listed as a condition but no fallback behavior is defined for the gap period if the external repo's release doesn't land in time. What happens to express eligibility while only one side of the contract is deployed?

3. **No explicit cost unknowns for the spike.** The first condition requires a spike to verify `create-implementation` without planning artifacts, but the effort/cost of that spike is not estimated. If the spike reveals the skill cannot work without planning artifacts, that changes the architecture significantly.

## Decision Soundness

1. **Conditions lack timeline and exit criteria.** "Spike to verify create-implementation" is actionable but unbounded — when is the spike done and what outcome triggers Go vs. redesign? The second condition ("coordinate before or in lockstep") needs a specific trigger (e.g., "if the triage-issue skill extension PR is not merged by release cut, the express flow labels are gated behind a feature flag").

2. **Effort estimate "M" is underspecified.** "M" alone is not testable or trackable. The assessment should define what "M" represents (e.g., 3-5 days, or a specific number of configuration changes + test scenarios).

3. **No discussion of the second-order outcome.** If the spike confirms `create-implementation` requires planning artifacts, the conditions say the path must "produce lightweight stubs or narrow eligibility." This architectural fork is acknowledged but not sized.

## Consistency

1. **Technical vs. Operational risk mismatch.** Technical identifies `create-implementation` without planning artifacts as "untested" (a meaningful risk), but Operational says "None" for skill gaps. If the skill's behavior in express mode is uncharacterized, that is at minimum an uncertainty gap, not zero risk.

2. **"High" ROI expectation is premature.** Financial feasibility claims "High" ROI, but ROI depends on the technical spike outcome. If `create-implementation` cannot produce correct code without planning artifacts, the express path may require lightweight stubs, eroding some token savings. The ROI claim should be conditioned on the spike result.

## Reversibility

1. **No reversibility analysis.** The assessment does not address: if we proceed and the express path causes problems (incorrect implementations, classification errors, orphaned label states), can we cleanly back out? The changes are mostly additive (labels, flow rules), so reversibility is likely high, but this should be stated explicitly.

2. **No one-way-door identification.** The triage-issue skill verdict extension (external repo, new `complexity` field) creates coupling. If the schema changes later, both repos must migrate in sync. This is a mild one-way door — once shipped, reverting the `complexity` field means all consuming rules must also revert.

3. **Conditions lack an exit/rollback strategy.** The two conditions (spike, coordinate rollout) are prerequisites, not safety valves. There is no "if X goes wrong, we do Y" fallback plan.

## Outcome

**verdict: changes-requested**

The assessment is well-structured and covers the necessary dimensions, but requires the following before approval:

1. Record unstated assumptions via `/create-assumption` (Risk Coverage #1)
2. Add timeline or exit criteria to the two conditions (Decision Soundness #1)
3. Define "M" effort estimate concretely (Decision Soundness #2)
4. Address the technical/operational risk inconsistency (Consistency #1)
5. Add a reversibility statement and one-way-door identification (Reversibility #1-2)
6. Define rollback/fallback behavior if conditions are not met or the path fails (Reversibility #3)
