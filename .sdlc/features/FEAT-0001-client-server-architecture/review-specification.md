---
artifact: specification
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Ambiguities

1. **Session subject_type mapping for issue_comment events.** The `sessions.subject_type` field lists "issue", "pull_request", "push" as example values but does not define how `issue_comment` webhook events map to a subject type. If `issue_comment` events create sessions with `subject_type="issue"` (since they belong to an issue subject), this mapping should be documented explicitly. Without it, implementers must infer the mapping from context.

## Inconsistencies

1. **API versioning prefix vs documented paths.** The Technical Decisions table states endpoints use URL prefix-based versioning (`/v1/webhook`, `/v1/admin/repositories`) and that unversioned paths are aliases. However, every API contract in the document defines only unversioned paths (`POST /webhook`, `GET /health`, `POST /admin/repositories`, etc.). The aliasing mechanism is not specified (server-level redirect? dual route registration?), and no versioned-path responses are documented. Implementers have no contract for the `/v1/` variants.

2. **DELETE /admin/repositories/{owner}/{repo} missing 401 error response.** The endpoint requires admin authentication (per the Admin API Authentication section), yet its documented error responses only list 404 NOT_FOUND. The 401 UNAUTHORIZED case is omitted. Every other admin endpoint (PATCH, GET list) explicitly lists it.

3. **PATCH /admin/repositories/{owner}/{repo} missing 400 INVALID_INPUT error response.** The POST /admin/repositories endpoint documents a 400 INVALID_INPUT response for invalid inputs (e.g., missing required fields). The PATCH endpoint is missing a comparable error case for semantically invalid field values, even though it accepts overlapping field types.

## Incoherences

No issues found.

## Missing Information

1. **No single-repository GET endpoint.** The API defines `GET /admin/repositories` (list all) and `POST/PATCH/DELETE` mutations, but there is no `GET /admin/repositories/{owner}/{repo}` to retrieve a single repository's current state. Operators cannot inspect a single repo's configuration after initial registration or update except through the full list response.

## Implementability

No issues found.

## Reversibility

No issues found.

## Forward Compatibility

No issues found.
