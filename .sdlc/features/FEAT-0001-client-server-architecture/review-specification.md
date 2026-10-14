---
artifact: specification
verdict: approved
reviewed_at: 2026-06-28
---

## Ambiguities

No issues found.

## Inconsistencies

1. **`auth_type` field accepted but not returned in GET responses**: The POST and PATCH admin endpoints accept `auth_type` as an input field (stored in `repositories.metadata._auth_type`), but no GET endpoint returns it. The spec explicitly states `gh_token` and `gh_token_expires_at` are never returned (line 106), but is silent on `auth_type`. An operator who registers a repo with `auth_type: "installation"` cannot verify the setting via the read-back API. Either `auth_type` should appear in GET responses (mirroring how `version` is surfaced) or the omission should be documented.

2. **"goroutine" terminology**: Risk #1 (line 736) mentions a "background cleanup goroutine" — this is Go terminology. In Python this should be "background task" or "async task."

## Incoherences

No issues found.

## Missing Information

1. **No general 500 error response documented**: The webhook endpoint error table (lines 276-284) covers 400, 401, 404, 200 (skipped), 503, and 429, but omits 500. An unexpected exception (corrupt database, coding error, disk-full) would presumably return 500 with the standard error envelope, but this is not documented. Consumers cannot distinguish between a transient 503 (shutting down, retryable) and a permanent 500 (unexpected failure).

2. **Admin API rate limiting not specified**: The webhook endpoint has rate limiting (10 req/s per IP, burst 20). The admin API endpoints have no documented rate limiting. A misbehaving admin client (e.g., polling bug) has no protection.

## Implementability

No issues found.

## Reversibility

No issues found (migration rollback is acknowledged as manual in the Out of Scope section).

## Forward Compatibility

No issues found.
