---
artifact: plan
verdict: changes-requested
reviewed_at: 2026-06-28
---

# Review: Implementation Plan

## Completeness

**Finding C1 — Missing deployment/rollout phase.**
The plan ends at Phase 7 (Testing & Hardening) with no dedicated phase for production deployment, rollout strategy, or migration from the existing CLI-based model. The requirements state repos choose one deployment model, but the plan does not describe how existing CLI-driven repos migrate to the server, what the rollout order is (staged by repo, all-at-once, etc.), or what a production-ready deployment looks like (reverse proxy TLS termination, Docker registry, monitoring stack). Add a Phase 8 covering deployment, rollout, and migration steps.

## Feasibility

**Finding F1 — Phase 6 observability effort is underestimated.**
Phase 6 (Observability & Telemetry Instrumentation) is estimated at 4 person-days for 13 deliverables covering structured logging, counter/histogram/gauge metrics, OpenTelemetry tracing, Prometheus `/metrics` integration, a Grafana dashboard JSON model, PromQL alert rules, and SLO documentation. This is aggressive for a 2-person team. Recommend 6-8 person-days or trimming the dashboard/alert rule scope from the initial delivery.

## Dependencies

**Finding D1 — Docker image registry and distribution not identified.**
The plan specifies a Dockerfile and build step but does not identify the Docker image registry (Docker Hub, ECR, GCR, etc.) as a dependency. Without a registry, the container cannot be distributed to production hosts. Add a registry dependency row with contingency (e.g., `docker load` from a tarball if registry is unavailable).

## Risk Coverage

**Finding R1 — Token encryption key loss or compromise not in risk register.**
The plan introduces AES-256-GCM + HKDF token encryption (Phase 5) but does not list the risk of losing the `TOKEN_ENCRYPTION_KEY` (all encrypted tokens become undecryptable) or having it compromised (attacker can decrypt all stored tokens). Add these risks with mitigations (backup key to a secrets manager, key rotation documented in runbook).

**Finding R2 — SQLite database corruption risk not captured.**
The plan depends on a single SQLite file for all state but does not list the risk of database corruption (filesystem errors, unexpected power loss, Docker volume issues). Add a risk row with mitigation: WAL mode (already planned), periodic `VACUUM` or integrity checks, documented backup/restore procedure.

## Timeline Realism

**Finding T1 — No buffer after Phase 7 for integration and release.**
The timeline ends at Week 8 with Phase 7 (Testing & Hardening). There is no buffer for integration/certification activities, release approval, or deployment. If Phase 7 overruns or if integration issues surface between phases, the entire timeline slips with no slack. Consider adding at least one buffer week after Phase 7 for release validation.

## Reversibility

**Finding RV1 — No rollback procedure for schema migrations.**
The plan includes numbered SQL migration files applied on startup but does not describe how to roll back a migration if a deployment causes issues. Add a rollback strategy for each migration (reverse migration files or documented restore-from-backup procedure).

**Finding RV2 — Token re-encryption is a one-way-door not flagged as such.**
Re-encrypting tokens with a new key (Phase 5) is irreversible unless the old key is retained. The plan correctly uses `TOKEN_ENCRYPTION_KEY_OLD` for transitions but does not flag this as a one-way-door commitment that requires careful sequencing and verification before discarding the old key.

**Finding RV3 — DELETE /admin/repositories cascade is destructive but not flagged.**
The `DELETE /admin/repositories/{owner}/{repo}` endpoint cascades to delete all sessions and events for that repository (ON DELETE CASCADE). The plan does not flag this as an irreversible data-loss action. Add a warning or confirmation step to the plan's description of this endpoint.
