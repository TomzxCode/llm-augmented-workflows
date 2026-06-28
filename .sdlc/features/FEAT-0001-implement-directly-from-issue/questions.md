# Questions

Open questions from requirements review (FEAT-0001):

1. What default criteria should distinguish a "simple feature" eligible for the express path from a "complex feature" requiring the full pipeline? (FR-01 specifies configurable criteria but does not define defaults.)

2. Should the express path default to a human-applied label (e.g., `llmaw:quick-implement`) or should the triage agent classify autonomously? (FR-01 and FR-06 support both; the default mode is unspecified.)

3. What specific format/content should the express-path artifact trail contain? (FR-03 requires a minimal artifact but does not specify its structure.)

4. How should metrics be exposed to the project owner? Via GitHub issue comments, a dashboard, or logs? (FR-07 requires metrics but the mechanism is open.)

5. How many features in the existing issue tracker would qualify for the express path? Usage data is absent; understanding frequency would strengthen implementation priority.
6. Should express-path eligibility be decided at triage time (extending the triage-issue skill's verdict) or as a separate routing step after triage? (From existing-solutions review.)
7. How should the express path handle the initial issue triage record? Options: consume triage verdict as-is, add a new triage class, or re-classify after triage. (From existing-solutions review.)
