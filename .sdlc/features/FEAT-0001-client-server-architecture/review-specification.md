---
artifact: specification
verdict: changes-requested
reviewed_at: 2026-06-28
---

# Specification Review: Client/Server architecture (revision 3)

## Ambiguities

1. **Session expiry detection at load time**: The spec states that expired sessions are handled by a background reaper and that "when a new webhook event arrives for an expired session, the server creates a fresh session instead of loading the stale one" (line 111). However, it does not specify how the server determines a session is expired at load time before the reaper deletes it. The reaper runs hourly; between runs, expired rows still exist. The server needs an explicit `updated_at` vs. `SESSION_TTL_HOURS` check on every session load. The current language conflates reaper-based deletion with load-time expiry detection, which are separate concerns.

## Inconsistencies

1. **Duplicate delivery HTTP status in Technical Decisions vs. API contract**: The Technical Decisions table (line 632) states "Duplicates get HTTP 409" but the API contract (line 244) returns HTTP 200 with `status: "skipped"`. The response shape does include a `reason` field on the 200 response, but the 409 claim in the Technical Decisions is stale and directly contradicts the API contract.

2. **Token encryption mode detection**: Line 87 says "If `TOKEN_ENCRYPTION_KEY_OLD` is not provided, a normal startup proceeds (existing tokens are decrypted with `TOKEN_ENCRYPTION_KEY`)." Line 91 says "To decrypt (returning to development mode), set `TOKEN_ENCRYPTION_KEY` to the current key and `TOKEN_ENCRYPTION_KEY_OLD` to empty — the server decrypts all tokens to plaintext." Both conditions (`TOKEN_ENCRYPTION_KEY_OLD` absent/empty) describe the same inputs but dictate different behaviors (normal decryption vs. plaintext migration). The spec must define how the server distinguishes these two modes, for example by reserving the empty-string value for the decrypt-to-plaintext path and treating a missing env var as normal startup.

## Incoherences

1. **Admin API optionality vs. dependency**: All admin endpoints are labeled "optional (FR-09)" in their headings, yet they are the only documented mechanism for repository registration. The "Out of Scope" section (line 655) suggests "manual registration via the admin API or direct SQLite insert" as alternatives. If the admin API is optional and direct SQL inserts are the fallback, the spec should either (a) mandate a minimal registration endpoint as Must (not May), or (b) provide a documented SQL script and configuration workflow as the primary path, making the REST API a convenience layer. The current framing implies the API can be omitted, which would leave first-time deployers with no documented registration workflow.

## Missing Information

1. **Deregistration cascade behavior**: `DELETE /admin/repositories/{owner}/{repo}` does not specify whether deleting a repository cascades to its `sessions` and `webhook_events` rows, or orphans them. If sessions are orphaned, the session reaper will eventually clean them up (via `repo_id` FK — though FK behavior is not specified either). If FK cascading is intended, the schema must declare it. This affects both data integrity and the reaper's query logic.

2. **Session initial status on insert**: The sequence diagram (lines 531-537) inserts a `webhook_events` row before returning HTTP 200, but does not specify the initial `status` value. The `status` enum includes "received", "processing", "completed", "failed", "skipped". The row should start as "received" or "processing", but this is not documented.

3. **GitHub token scopes**: The `gh_token` field is described as a "GitHub installation token or PAT for outbound API calls" but no required scopes or permissions are listed. Implementors need to know which scopes the token must have (e.g., `issues:write`, `pull_requests:write`, `contents:write`).

4. **Thread pool size not configurable**: The maximum of 20 workers is hardcoded in the description (line 629). Making this configurable via an environment variable would support deployments with different concurrency requirements (e.g., 5 repos vs. 50 repos).

5. **Admin token strength requirement**: No minimum length or character requirements are specified for `ADMIN_TOKEN`. A weak token is a security risk for the admin API.

## Implementability

1. **`asyncio.Lock` not thread-safe across `run_in_executor`**: Line 642 proposes "a per-session `asyncio.Lock` serializes writes within each session." However, dispatch to the agent pipeline uses `run_in_executor` (thread pool, line 629), which runs code in a separate thread. `asyncio.Lock` is not thread-safe and must only be used from within the same event loop thread. Using it across threads would cause undefined behavior. This should be `threading.Lock` or, if the SQLite writes remain in the async path, the lock must be acquired before dispatching to the thread pool and released only after the async write completes.

2. **Token encryption state machine complexity**: The three-way startup logic (normal startup with `TOKEN_ENCRYPTION_KEY`, key rotation with `TOKEN_ENCRYPTION_KEY` + `TOKEN_ENCRYPTION_KEY_OLD`, decrypt-to-plaintext with empty `TOKEN_ENCRYPTION_KEY_OLD`) introduces a non-trivial state machine. This is testable but error-prone. Consider simplifying: split the decrypt-to-plaintext path into a separate one-shot maintenance command (like `llmaw-admin reencrypt-tokens` already handles re-encryption) rather than wiring it into the startup branch detection.

## Reversibility

1. **Session data compatibility across version switches**: If a repository's `version` is changed from `v2-canary` back to `v1`, existing session data (conversation_history, context) may contain fields or formats produced by the v2-canary configuration. The spec does not address whether the `v1` config bundle tolerates v2-structured JSON, or whether sessions should be reset on version change. This is a one-way-door concern: a version rollback could corrupt in-flight sessions.

2. **Encryption-to-plaintext path**: The spec includes a documented path back to plaintext for development/disaster recovery (line 91). While scoped to development, this creates a latent risk: an operator could accidentally trigger plaintext migration in a production environment. Consider removing the startup-based decrypt path entirely and offering a separate offline tool instead.

## Forward Compatibility

1. **Version removal from `versions.yaml`**: The spec defines `versions.yaml` as the source of available config bundles but does not specify behavior when a version referenced by a `repositories.version` row is removed from the file. The server should define a fallback (e.g., fall back to `v1` defaults and log a warning) to avoid a crash loop for those repositories.
