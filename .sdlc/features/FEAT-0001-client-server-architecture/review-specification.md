---
artifact: specification
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Ambiguities

**Session TTL environment variable naming.** The session expiry paragraph references `SESSION_TTL_HOURS` as the configurable value ("compares `updated_at` against `SESSION_TTL_HOURS` (configurable, default 168)") but then immediately states "The `SESSIONS_MAX_AGE_HOURS` environment variable overrides the default TTL." It is unclear whether these are aliases for the same variable, one is the code constant and the other the env var override, or this is a naming inconsistency. An implementer cannot tell which name to use.

## Inconsistencies

**`updated_at` missing from repository API responses.** The `repositories` table schema defines `updated_at` (not null), but no admin API response (`GET /admin/repositories`, `GET /admin/repositories/{owner}/{repo}`, `POST /admin/repositories`, `PATCH /admin/repositories/{owner}/{repo}`) includes it. Unlike `secret_token` and `gh_token` (whose exclusion is explicitly documented), `updated_at`'s absence is not addressed.

**`error` field missing from webhook event list responses.** The `webhook_events` table includes a nullable `error` column, but the `GET /admin/events` response schema does not include it, nor is its exclusion documented (the spec only documents that `payload` is excluded).

## Incoherences

**Token encryption key rotation "unset" language.** The spec states "After a successful rotation, `TOKEN_ENCRYPTION_KEY_OLD` is unset and only `TOKEN_ENCRYPTION_KEY` is retained." Environment variables cannot be unset from the deployment environment by a running process without explicit code to clear `os.environ`. If the intent is that this happens at next restart after the operator removes the variable, the wording is misleading. If the intent is that the server clears it from `os.environ` after rotation, this should be stated explicitly.

## Missing Information

**GitHub App installation token refresh.** The `gh_token` field stores "GitHub installation token or PAT for outbound API calls." PATs are long-lived, but GitHub App installation tokens expire after 1 hour and must be periodically refreshed. The spec provides no mechanism, endpoint, or guidance for refreshing installation tokens. A production server relying on installation tokens would fail after 1 hour without this.

**No SLA or uptime targets.** The spec defines performance targets (NFR-03: 5s dispatch) and capacity targets (NFR-04: 10 concurrent repos) but does not state any availability SLA, maintenance window policy, or uptime target. Operators have no guidance on expected service level.

## Implementability

No issues found.

## Reversibility

No issues found.

## Forward Compatibility

No issues found.
