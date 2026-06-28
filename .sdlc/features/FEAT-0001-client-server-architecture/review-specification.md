---
artifact: specification
verdict: changes-requested
reviewed_at: 2026-06-28
---

# Specification Review: Client/Server architecture (revision 2)

## Ambiguities

1. **Unhandled event type behavior**: The spec defines FR-01 for "push, pull_request, issue_comment, issues" events but the POST /webhook endpoint does not specify what happens when an unsupported event type (e.g., `star`, `member`, `fork`) is received. Does the server accept it with 200 and tag it as `status: skipped`, or reject with 400? Without this, the behavior for a majority of GitHub event types is undefined.

## Inconsistencies

1. **POST/PATCH /admin/repositories response omits `version` and `created_at`**: The 201 response returns `id`, `owner`, `repo`, `active` but not `version` (which is accepted in the request) or `created_at`. The GET /admin/repositories response includes both `version` and `created_at`. The PATCH response similarly omits `version`. The response shapes should be consistent or the divergence explicitly justified.

2. **Event ID field naming across endpoints**: `POST /webhook` returns `event_id` but `GET /admin/events` returns `id` for the same logical value. This is a minor naming inconsistency that API consumers must handle differently per endpoint.

## Incoherences

1. **409 "not an error" with conflict status**: The 409 duplicate delivery response is described as "not an error; it is the expected outcome of GitHub's at-least-once delivery guarantee." Yet it uses HTTP 409 (Conflict), conventionally an error status. The body uses `"status": "skipped"` rather than the uniform `"status": "error"` envelope, diverging from all other error responses. If this is truly not an error, HTTP 200 with `status: "skipped"` would be more consistent.

## Missing Information

1. **Unsupported event type handling**: (Related to Ambiguities #1.) No requirement or acceptance criterion covers how the server behaves for event types it does not handle. The spec should document the behavior (e.g., return 200 with `status: "skipped"` and insert a webhook_events row, or reject with 400).

2. **`versions.yaml` schema undefined**: The spec relies on a YAML file at `/etc/llmaw/versions.yaml` to define available agent configuration bundles for canary deployments (FR-10), but the schema of this file is not specified. Implementors cannot act on this without the expected structure. This blocks FR-10 implementation.

## Implementability

1. **Bulk token re-encryption at startup**: The key rotation procedure reads every token from the database, decrypts with `TOKEN_ENCRYPTION_KEY_OLD`, and re-encrypts with `TOKEN_ENCRYPTION_KEY` at startup. For deployments with many repositories, this could significantly delay server readiness. No progress logging, timeout, or deferral mechanism is specified. Consider adding a startup timeout, batched processing with progress logging, or a separate maintenance command.

## Reversibility

No issues found. All previously identified issues have been addressed:
- Encryption/decryption migration is now bidirectional.
- Schema migration convention (numbered SQL files + manual rollback) is documented.
- CLI path preservation remains in place.
- Canary routing (`version` field) is trivially reversible.

## Forward Compatibility

No issues found. The spec is thorough:
- Unknown field tolerance is documented across all endpoints and data models.
- Open enums with additive-only guarantees for `webhook_events.status`.
- `metadata` JSON column provides a structured extension point.
- URL-prefix API versioning with documented deprecation window.
- Consumers instructed to handle unknown error codes as generic 5xx errors.
