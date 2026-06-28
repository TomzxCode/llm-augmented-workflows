---
artifact: specification
verdict: changes-requested
reviewed_at: 2026-06-28
---

# Specification Review: Client/Server architecture

## Ambiguities

1. **Token encryption key rotation mechanism**. The spec states "Key rotation is performed by re-encrypting all stored tokens with the new key on server restart." Simply changing the `TOKEN_ENCRYPTION_KEY` env var and restarting would make existing encrypted tokens undecryptable — the new key cannot decrypt data encrypted with the old key. Rotation requires the old key to be provided alongside the new key (e.g., `TOKEN_ENCRYPTION_KEY_OLD`) so the server can decrypt-then-re-encrypt on startup. Without this detail, an operator following the description as written will lock themselves out of stored tokens.

2. **Skill file distribution timing**. The Technical Decisions table says "cloned at container startup" but risk #4 says "cloning at first webhook event or at startup." These are different timings: startup means the clone blocks readiness; first-event means the first webhook bears the cold-start latency. The spec should pick one and describe the trade-off.

3. **`version` field semantics**. The health response shows `"version": "1.0.0"` (a software-version-looking string) but the Technical Decisions state this is "the API version, not the server build." These are semantically different — API version follows the contract, server build follows releases. The field name and example value should match the stated semantics.

## Inconsistencies

1. **Error response envelope mismatch**. POST /webhook 401 returns `{"status": "rejected", "reason": "invalid_signature"}` but every other error response (400, 404, 503, all admin errors) uses `{"status": "error", "error": {"code": "...", "message": "..."}}`. The webhook 401 should either adopt the uniform envelope or document an explicit rationale for the different format.

2. **POST /webhook 409 response includes `event_id` for duplicates**. The 409 response returns `"event_id": "uuid"` but the sequence diagram shows the dedup check (unique constraint on `delivery_id`) happens before any new event row is inserted. The `event_id` must come from the existing event row — the spec should clarify that the response returns the existing event's ID, not a new one.

## Incoherences

1. **Canary deployments in a single container**. FR-10 requires supporting multiple agent versions simultaneously and the spec reserves `repositories.version` for this. But NFR-07 mandates a single Docker container with no external dependencies. The spec never explains how different agent versions coexist within one container — different model configs, different prompt templates, or different engine builds? The architecture appears self-contradictory (multi-version requirement inside a single-container constraint) without elaboration.

2. **Rate-limit reset semantics**. The in-memory token bucket "resets on server restart" but the spec promises `X-RateLimit-Reset` headers in 429 responses. If state is purely in-memory, the reset timestamp is computed relative to the refill window (consistent), but headers returned before the restart become stale references after it. This is a minor tension between stateless-in-memory and the header contract consumers depend on.

## Missing Information

1. **Session expiry and cleanup**. The `/health` endpoint reports `active_sessions` as "Count of non-expired sessions" but no session expiry or reaper mechanism is defined anywhere. When do sessions become eligible for cleanup? Is there a TTL? Without a policy, the `sessions` table grows indefinitely.

2. **Webhook events retention**. The `webhook_events` table has no retention or archival policy. It serves as an idempotency log and audit trail, but without a retention window it will grow unbounded, impacting storage and query performance over time.

3. **Admin token rotation transition path**. The spec says rotation is "performed by restarting the server with a new ADMIN_TOKEN value." This is a hard cutover — all existing admin bearer tokens are invalidated immediately. There is no grace period where both old and new tokens are accepted. Any automated admin client will experience disruption on restart.

4. **Rate-limit configuration**. The values (10 req/s per IP, burst 20) are hardcoded in the spec. Are these configurable via environment variables? Different deployments may need different thresholds.

5. **Missing indexes on lookup columns**. The `repositories` table relies on a composite unique constraint on `(owner, repo)` but no index is specified for this lookup (used on every webhook event). The `sessions` table has no index on `(repo_id, subject_type, subject_id)` despite being the lookup key for session restoration. For SQLite, explicit indexes on these lookup paths are important for performance (NFR-03, NFR-04).

## Implementability

1. **Token re-encryption on key rotation is unimplementable as described**. As noted under Ambiguities, the rotation procedure requires the old key to be available during restart. The current text describes an operation that cannot work.

2. **Admin token hard cutover**. As noted under Missing Information, rotating ADMIN_TOKEN via restart invalidates all active admin sessions instantly. A practical implementation would need to accept both old and new tokens during a transition window.

3. **Canary routing mechanism unspecified**. The `repositories.version` field is reserved for canary deployments but the spec does not describe how the server uses this field to route to different agent versions. Without a mechanism, the field cannot be implemented.

## Reversibility

1. **No decryption path if encryption is disabled**. Once `TOKEN_ENCRYPTION_KEY` is set and tokens are encrypted, operators cannot simply remove the env var to return to plaintext — encrypted tokens become unreadable. There is no documented decryption or migration procedure.

2. **No migration framework for schema changes**. The spec notes this as out of scope ("CREATE TABLE IF NOT EXISTS"), meaning schema changes lack both a forward migration path and a rollback path.

3. **CLI path preservation is good**. The existing CLI/CLI-workflow path is preserved and unchanged, providing a clean fallback. Behavioral identity verification (risk #5) ensures equivalence before production promotion. This is well handled.

## Forward Compatibility

No issues found. Unknown field tolerance is specified across all endpoints, enum values are additive-only with a documented deprecation window, API versioning uses URL prefixes with a deprecation policy, and the `metadata` JSON column provides an extension mechanism.
