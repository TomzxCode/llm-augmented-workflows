---
artifact: specification
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Ambiguities

**`auth_type` and `gh_token_expires_at` field handling in admin API.** The spec states these are accepted as optional fields in `POST /admin/repositories` and `PATCH /admin/repositories/{owner}/{repo}` (line 105), but they are not listed in the documented request body schemas (lines 349-357 and 421-427). It is unclear whether these are first-class fields with dedicated columns or stored in `repositories.metadata` alongside user-provided extension fields. The defaulting behavior (`auth_type` defaults to `"pat"`) suggests special handling, but the schema tables don't reflect this.

**`refresh_failure_count` counter reset.** The spec says the counter is incremented on refresh failures and after 3 consecutive failures the repo is deactivated (line 104). It does not specify when or how the counter is reset (e.g., on a successful refresh), nor what "consecutive" means — across what time window? A repo with a history of failures could remain permanently deactivated even after the underlying issue is resolved.

## Inconsistencies

**`webhook_events` foreign key behavior.** The data model table for `webhook_events` (lines 168-180) specifies `repo_id` as "FK → repositories.id, not null" but does not mention `ON DELETE CASCADE`. The prose at line 132-133 asserts that `webhook_events` has `ON DELETE CASCADE`. The table definition and the prose are inconsistent — an implementer cannot tell which is correct.

## Incoherences

No issues found.

## Missing Information

**`repositories.metadata` namespace collision risk.** The `metadata` JSON column serves dual purpose: it stores user-provided extension fields from API requests (line 358) and system-managed operational fields (`auth_type`, `gh_token_expires_at`, `refresh_failure_count`, line 99-104). There is no documented namespace, prefix, or separation convention. A `PATCH /admin/repositories` request that includes a field like `auth_type` would silently overwrite the system-managed value.

## Implementability

**Per-session `threading.Lock` lifecycle undefined.** The spec proposes a `threading.Lock` per `(repo_id, subject_type, subject_id)` to serialize writes (line 732), but does not describe how locks are created, stored, looked up, or garbage-collected as sessions expire. Without a cleanup strategy, locks accumulate indefinitely, creating a memory leak.

## Reversibility

No issues found.

## Forward Compatibility

No issues found.
