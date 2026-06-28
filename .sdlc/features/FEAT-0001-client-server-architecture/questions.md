---
feature: FEAT-0001-client-server-architecture
source: needs-assessment.md
---

# Open Questions

1. What specific limitations of GitHub Actions runners have users encountered (if any)?
2. Is persistent agent state a real requirement for the expected use cases, or is stateless event-driven automation sufficient?
3. What is the operational cost tolerance for maintaining a hosted server versus the current zero-infrastructure model?

## Resolved

- Session state persistence (was Q3 in requirements): resolved to local disk (SQLite) with Docker volume mount, per conflict resolution in requirements.md.
- **Env var racing for concurrent multi-repo execution (codebase-analysis Q1):** Resolved via parameter injection with env var fallback (approach b). `run_steps._current_subject()`, `_gh()`, `apply_labels()` and `apply_outcome.apply()` now accept optional parameters for subject context and GH token. The server path passes all context as function parameters; the CLI path uses env var fallback. No env vars are written by the server path, eliminating the race.
- **`_current_subject()` env var source (codebase-analysis Q2):** Resolved together with Q1 via parameter injection.
