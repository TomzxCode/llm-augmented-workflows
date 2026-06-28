---
artifact: specification
verdict: changes-requested
reviewed_at: 2026-06-28
---

# Specification Review: Client/Server architecture

## Ambiguities

1. **Retry attempt count vs. shown retries in sequence diagram.** The Retry Strategy table (line 406) specifies "3 attempts, exponential backoff (1s/2s/4s)". The retry sequence diagram (lines 370-396) shows only 2 retries (wait 1s, wait 2s) before success on the third attempt — but the 4s backoff value from the table never appears. Either the sequence should show a third retry with a 4s wait, or the table and sequence should be aligned on the exact retry count and delay values.

2. **Per-repo lock vs. per-session lock.** The SQLite contention risk (line 417) says "per-repo asyncio.Lock serializes writes per session". It is unclear whether the lock is scoped per repository (serializing all sessions for that repo) or per individual session. These have different contention profiles.

## Inconsistencies

1. **Missing admin endpoints for FR-09.** FR-09 requires endpoints to "view registered repositories, active sessions, and execution logs." The spec only provides POST/DELETE `/admin/repositories`. There is no GET endpoint to list repositories, no endpoint to view active sessions, and no endpoint to access execution logs. These requirements from FR-09 are not reflected in the API Contracts section.

## Incoherences

No issues found.

## Missing Information

1. **Admin API authentication.** The admin endpoints (`POST /admin/repositories`, `DELETE /admin/repositories/{owner}/{repo}`) have no authentication or authorization mechanism specified. Anyone who can reach the server can register or deregister repositories. The spec should specify how admin requests are authenticated (e.g., shared admin token, mTLS, IP allowlist).

2. **GitHub credentials at rest.** The `repositories.gh_token` field stores sensitive GitHub credentials (PAT or installation token) as plain text. There is no mention of encryption at rest for this field, nor a mechanism for secure secret injection (e.g., mounted secrets, environment variables, or an external secrets store).

3. **No API versioning strategy.** The spec uses a `version` field in the health response and `repositories.version` for canary deployments, but does not define an API versioning scheme for the HTTP endpoints (e.g., URL prefix `/v1/webhook`, Accept header negotiation). Consumers have no way to pin to a specific API version.

4. **Rate limiting specification.** The 429 response (line 183) is listed as "optional, if rate limiting is added later." No rate limiting strategy, thresholds, or headers (RateLimit-Remaining, Retry-After) are specified. Without this, the server has no protection against webhook storms.

5. **TLS deployment model.** The spec notes "No TLS termination in the server" (risk 7, line 422) and delegates it to a reverse proxy, but provides no guidance on how TLS is configured in production, leaving a security gap unaddressed in the specification.

6. **Webhook secret rotation.** No endpoint or mechanism for rotating `repositories.secret_token` is provided. Out of Scope lists this as manual (direct SQLite update), but for a production service this should have a defined process.

## Implementability

1. **Retry only on CalledProcessError.** The retry strategy (line 406) limits retries to `CalledProcessError` (non-zero subprocess exit). If the `gh` CLI exits 0 but the GitHub API response communicates a rate-limit or transient error, the retry logic will not trigger. The retry should also cover cases where the subprocess output indicates an API-level retryable failure.

2. **Thread pool dispatch after HTTP response.** The sequence diagram (lines 316-317) shows the server returning HTTP 200 before dispatching to the thread pool. If `run_in_executor` submission itself blocks due to a full queue, the response is sent but dispatch fails silently. The spec should clarify how thread pool submission failures are surfaced (log + update webhook_events status to "failed").

## Reversibility

No issues found. The CLI path is preserved and unchanged, providing a clean fallback. Crash recovery via Docker volume + SQLite WAL is well-specified. The behavioral identity verification (risk 5) ensures equivalence between both paths before the server is promoted to production use.

## Forward Compatibility

1. **No API versioning contract.** Without a versioning strategy (as noted under Missing Information), future API changes cannot be introduced without breaking existing consumers. The spec should document a versioning policy (e.g., additive-only within /v1, with /v2 for breaking changes) and a deprecation window for old versions.

2. **No consumer guidance for enum additions.** The spec states that `webhook_events.status` is an open enum and `repositories` has a `metadata` JSON column, but does not specify how new enum values will be introduced or how long before old values are removed. A documented policy (e.g., "new values are additive only; removal is communicated one major version in advance") would strengthen forward compatibility.
