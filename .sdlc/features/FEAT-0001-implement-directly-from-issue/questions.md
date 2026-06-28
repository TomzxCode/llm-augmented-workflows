# Questions

Open questions from requirements review (FEAT-0001):

1. What default criteria should distinguish a "simple feature" eligible for the express path from a "complex feature" requiring the full pipeline? (FR-01 specifies configurable criteria but does not define defaults.)

2. Should the express path default to a human-applied label (e.g., `llmaw:quick-implement`) or should the triage agent classify autonomously? (FR-01 and FR-06 support both; the default mode is unspecified.)

3. What specific format/content should the express-path artifact trail contain? (FR-03 requires a minimal artifact but does not specify its structure.)

4. How should metrics be exposed to the project owner? Via GitHub issue comments, a dashboard, or logs? (FR-07 requires metrics but the mechanism is open.)

5. How many features in the existing issue tracker would qualify for the express path? Usage data is absent; understanding frequency would strengthen implementation priority.

6. Should express-path eligibility be decided at triage time (extending the triage-issue skill's verdict) or as a separate routing step after triage? (From existing-solutions review.)

7. How should the express path handle the initial issue triage record? Options: consume triage verdict as-is, add a new triage class, or re-classify after triage. (From existing-solutions review.)

Open questions from feasibility review:

8. What is the rollback/exit strategy if the express path fails in production (e.g., incorrect implementations, classification errors, orphaned label states)? The feasibility assessment conditions do not specify how to back out.

9. What does the "M" effort estimate represent in concrete terms (person-days, story points, or calendar time)? Without a definition the estimate is untestable.

10. Is the assumption that the flows engine can be extended with new express-flow rules without refactoring existing flow matching logic validated? This should be recorded as an assumption and verified.

11. Does the triage-issue skill external repo have a release process that guarantees lockstep shipping with this project's flow config? If not, what fallback behavior applies during the gap?

Open questions from specification review:

12. How does the express flow rule verify label origin for anti-spoofing (NFR-05) without engine changes? This contradicts the zero-engine-changes design decision and must be resolved before implementation.

13. Can `create-implementation` produce output from "issue body + labels only" without modification? The spec should verify this before shipping the express path.

14. How does `defaults.express` config flow to the triage classification logic? No engine component currently reads these keys.

Open questions from telemetry review (revision 1):

15. How should the token savings metric be computed during ongoing operation when there is no paired full-pipeline run for the same express-path issue? The current comparison methodology requires a counterfactual that does not exist in production.

16. Should upstream infrastructure failures (triage crashes, label application failures, workflow dispatch errors) be instrumented as events in the telemetry plan, or is GitHub Actions run log monitoring sufficient for V1?

Open questions from telemetry review (revision 2):

17. Should `issue_opened` be defined as a custom analytics event with typed properties, or explicitly documented as a GitHub-native event in the funnel?

18. Should `express_eligibility_set` be renamed to capture both express-eligible and full-pipeline routing outcomes, or should a separate event be created for the ineligible path?

19. Should `full_pipeline_triggered` fire simultaneously with `express_eligibility_set` for ineligible issues, or should one be derived from the other to avoid double-counting?

20. Should `workflow_step_failed` exclude `create-implementation` from its `step_name` values to avoid overlap with `implementation_failed`, or should the failure-mode boundary between the two events be documented explicitly?
