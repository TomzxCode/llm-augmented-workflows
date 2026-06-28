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
- **Env var racing for concurrent multi-repo execution (codebase-analysis Q1):** The analysis identifies this risk but does not resolve it. The server must choose one of: (a) use thread-local storage to isolate env per repo, (b) refactor leaf modules to accept tokens as parameters, or (c) restrict to single-threaded per-repo execution. This must be resolved before implementation.
