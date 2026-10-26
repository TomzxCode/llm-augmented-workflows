# Open Questions

Resolved from needs-assessment.md review.

1. Which specific CLI tools (beyond opencode) are most requested, and what are their runtime requirements (installation, permissions, output format)?
2. Is there actual user demand beyond the issue author, or is this a speculative enhancement?
3. What is the engineering effort to abstract the agent step vs. the expected adoption benefit?
4. What specific threshold (how many users/teams, over what timeframe) would constitute sufficient evidence of demand for this feature?

Carried over from requirements.md review.

5. Should verdict parsers be standalone executables or could they be inline scripts (e.g., a regex or exit-code mapping in YAML config)? A simpler config-based parser (map exit codes to verdicts) may cover most use cases without requiring users to write scripts.
6. What is the minimum supported interface for a verdict parser — does it receive stdin only, or also env vars with step metadata?
7. How should the engine discover built-in parsers for runtimes that are not installed at engine start (e.g., a parser registered by a third-party package)?
8. What is the upgrade/migration path for existing workflows that use `shell:` to simulate agent steps today?
9. Should the engine support an admin-enforced allowlist of approved `agent.command` values to satisfy the security/compliance stakeholder requirement to "mandate a specific approved AI tool"?
10. Should per-runtime sandbox configuration be supported (e.g., some runtimes need network access, others do not), or is the single global NFR-03 setting sufficient?
