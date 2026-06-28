---
feature: FEAT-0001-client-server-architecture
source: needs-assessment.md
---

# Open Questions

1. What specific limitations of GitHub Actions runners have users encountered (if any)?
2. Is persistent agent state a real requirement for the expected use cases, or is stateless event-driven automation sufficient?
3. What is the operational cost tolerance for maintaining a hosted server versus the current zero-infrastructure model?
4. How should skill files be distributed in the server model — cloned at container start, mounted as a volume, or fetched on first use? This affects startup time and Docker image size.
5. Does the server need a `FORCE_RULE_ID`-like bypass (e.g., for admin API testing), or is that only relevant to the GitHub Actions workflow dispatch path?

6. How should unsupported GitHub event types (e.g., `star`, `member`) be handled by the webhook endpoint — accepted with 200 and skipped, or rejected with 400?
7. What is the expected schema of `versions.yaml` for canary deployment configuration (model identifier, prompt template, skill repo reference, max iteration count)?
8. Should the POST/PATCH /admin/repositories response include `version` and `created_at` for consistency with the GET list response?

9. How should GitHub App installation tokens be refreshed? The `gh_token` field accepts either a PAT or an installation token, but installation tokens expire after 1 hour. The server needs a periodic refresh mechanism (e.g., using the `GH_APP_ID` and `GH_APP_PRIVATE_KEY` to generate a new JWT and exchange it for a fresh installation token) or should document that only PATs are supported in the initial version.

## Resolved

- Session state persistence (was Q3 in requirements): resolved to local disk (SQLite) with Docker volume mount, per conflict resolution in requirements.md.
- **Env var racing for concurrent multi-repo execution (codebase-analysis Q1):** Resolved via parameter injection with env var fallback (approach b). `run_steps._current_subject()`, `_gh()`, `apply_labels()` and `apply_outcome.apply()` now accept optional parameters for subject context and GH token. The server path passes all context as function parameters; the CLI path uses env var fallback. No env vars are written by the server path, eliminating the race.
- **`_current_subject()` env var source (codebase-analysis Q2):** Resolved together with Q1 via parameter injection.
