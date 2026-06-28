---
issue: "#17"
title: "Implement directly from issue"
status: in-review
revision: 1
---

# Implementation Plan: Implement directly from issue

## Goal

Add a lightweight express path that routes eligible issues directly from triage to implementation, skipping intermediate planning phases while producing a minimal traceability artifact. The express path operates alongside the existing feature and bugfix flows without modifying them.

> **Revision note:** Effort estimates increased ~40% from initial draft to account for cross-repo coordination, review cycles, and integration testing. Phase 4 split into Phase 4 (telemetry events + logging) and Phase 5 (alerting + dry-run tests). Dependencies table now includes critical-path markers and contingency plans. Risk register expanded per spec. Timeline adjusted with explicit buffers and per-phase resourcing.

## Phases

### Phase 1: Triage-Issue Skill Extension

**Goal:** The `triage-issue` skill emits an optional `complexity` field in its verdict YAML.
**Effort:** 3 person-days (includes cross-repo PR in `tomzx/agents`, review iteration, deployment coordination)
**Depends on:** None
**Resource:** 1 developer (single-owner, well-scoped change)

**Deliverables:**
- [ ] Add `complexity: low | medium | high` optional field to triage-issue skill's `$OUTCOME_YAML` output
- [ ] Add complexity assessment logic to the triage prompt (classify based on scope, cross-cutting concerns, file count, dependencies)
- [ ] When complexity is absent, consumers treat issue as "not express-eligible" (backward compatible)

### Phase 2: Express Flow Configuration

**Goal:** New `express` flow in `flows.yml` with two rules, config block, and on_outcome handlers.
**Effort:** 4 person-days (6 deliverables including label definitions, two rules, config block, on_outcome handlers, triage flow updates, and integration testing)
**Depends on:** Phase 1 (either order safe per spec, but logical dependency exists; can parallelize prep work)
**Resource:** 1 developer (2nd developer can assist with label definitions and config block in parallel)

**Deliverables:**
- [ ] Add `defaults.express` config block with eligibility criteria, model override, timeout, and `comment_on_classification`
- [ ] Add `express-implement-from-eligible` rule matching `issues:labeled` + `llmaw:express-eligible` label
- [ ] Add `express-quick-implement` rule matching `issues:labeled` + `llmaw:quick-implement` label
- [ ] Update triage flow `on_outcome` to read complexity verdict + config and apply either `llmaw:express-eligible` or `llmaw:feature-request`
- [ ] Add express flow `on_outcome` handlers for `approved` (set `llmaw:express-done`, post comment) and `failed` (set `llmaw:express-failed`, post error comment)
- [ ] Add label definitions for `llmaw:express-eligible`, `llmaw:quick-implement`, `llmaw:express-done`, `llmaw:express-failed`

### Phase 3: Express Decision Artifact

**Goal:** A minimal `express-decision.md` artifact is written for every express-path feature.
**Effort:** 1 person-day
**Depends on:** Phase 2
**Resource:** 1 developer

**Deliverables:**
- [ ] Implement `express-decision.md` artifact with schema_version, trigger, complexity, reason, implemented_at, outcome, pr_url
- [ ] Write artifact on implementation success or failure
- [ ] Ensure artifact follows `.sdlc/features/FEAT-NNNN-<slug>/express-decision.md` path convention

### Phase 4: Telemetry Events and Logging

**Goal:** All telemetry event emissions and structured logging from the telemetry plan are implemented.
**Effort:** 2 person-days
**Depends on:** Phases 1, 2
**Resource:** 1 developer

**Deliverables:**
- [ ] Emit structured `TELEMETRY_EVENT` log lines from `flows.yml` on_outcome handlers for: `classification_comment_posted`, `routing_decision_made`, `express_override_used`, `express_label_removed`
- [ ] Add telemetry event emission for `implementation_started`, `implementation_completed`, `implementation_failed` from the express flow and `create-implementation` skill outcome
- [ ] Add `workflow_step_failed` event emission from failure handlers in flows.yml
- [ ] Expose `token_input`, `token_output`, `duration_seconds` in `create-implementation` outcome YAML
- [ ] Implement express flow match logging (INFO level) and failure logging (ERROR level)
- [ ] Implement label state transition logging for all `llmaw:*` labels

### Phase 5: Alerting and Dry-Run Tests

**Goal:** Health monitoring, alert aggregation, and periodic verification of the express path are operational.
**Effort:** 2 person-days
**Depends on:** Phase 4 (telemetry events must be emitting before alerts can consume them)
**Resource:** 1 developer

**Deliverables:**
- [ ] Implement post-hoc alert aggregation logic (weekly summary computation of failure rates, token efficiency, timeout events)
- [ ] Implement periodic dry-run test workflow for express path health check
- [ ] Define rollback path: config toggle to disable express path in `defaults.express`, documented manual disable procedure
- [ ] Document that terminal labels (`llmaw:express-done`, `llmaw:express-failed`) are irreversible by automation — human intervention required to retry

### Phase 6: Verification and Hardening

**Goal:** Verify the express path works correctly against historical issues and meets NFR targets.
**Effort:** 4 person-days (3-5 historical test issues, quality comparison, CI verification, regression testing)
**Depends on:** Phases 1, 2, 3, 4, 5
**Resource:** 2 developers (one runs tests, one reviews output)

**Deliverables:**
- [ ] Run `create-implementation` skill against 3-5 historical issues with known PRs
- [ ] Compare express-path output against actual implementations for quality parity (NFR-02)
- [ ] Verify token consumption stays below 60% of full-pipeline baseline (NFR-01)
- [ ] Verify CI checks pass on generated PRs
- [ ] Verify that ineligible issues correctly fall through to the full pipeline
- [ ] Verify classification accuracy (false-positive rate below 20%)
- [ ] Verify label state machine transitions (happy path, failure, override, removal)
- [ ] Verify backward compatibility: existing feature and bugfix flows are unaffected
- [ ] Verify anti-spoofing: confirm `llmaw:express-eligible` is never set by human actors in testing (NFR-05)
- [ ] Verify `express-decision.md` with `failed` outcome does not interfere if issue is later re-processed through full pipeline

### Phase 7: Documentation and Rollout

**Goal:** Express path is documented, deployable, and monitored in production with a rollback plan.
**Effort:** 3 person-days (documentation, cross-repo deployment coordination, monitoring setup, rollback procedure)
**Depends on:** Phase 6
**Resource:** 1 developer

**Deliverables:**
- [ ] Update flows.yml documentation with express path rules and config
- [ ] Update README or project docs with express path overview
- [ ] Coordinate cross-repo deployment: update `triage-issue` skill in `tomzx/agents` first (or verify safe ordering per spec)
- [ ] Enable express path in production configuration (config toggle, not a code change)
- [ ] Set up initial monitoring (label-based queries, weekly alert review)
- [ ] Record baseline token consumption from first 5 express-path runs
- [ ] Document rollback procedure: set `defaults.express.timeout_minutes: 0` or remove express rules from `flows.yml` to disable the path; verify no active `llmaw:express-eligible` issues
- [ ] FR-07 (metrics dashboard) explicitly deferred to a follow-up phase pending usage volume

## Milestones

| Milestone | Phase | Success Criteria |
|---|---|---|
| M1: Triage emits complexity | Phase 1 | triage-issue skill's `$OUTCOME_YAML` contains `complexity` field on eligible issues |
| M2: Express flow operational | Phase 2 | A test issue labeled `llmaw:quick-implement` triggers the express flow and reaches `create-implementation` |
| M3: Artifact trail complete | Phase 3 | `express-decision.md` is written on both success and failure of express-path issues |
| M4: Telemetry live | Phase 4 | Structured TELEMETRY_EVENT log lines appear in GITHUB_STEP_SUMMARY; token_input and token_output captured in outcome YAML |
| M5: Health monitoring live | Phase 5 | Weekly alert summary produces valid output; dry-run workflow runs without error; rollback procedure documented |
| M6: Quality verified | Phase 6 | 3/3 historical test issues produce code quality equivalent to original implementations; token consumption below 60% of full pipeline; anti-spoofing verified |
| M7: Production ready | Phase 7 | Express path enabled via config toggle; monitoring queries return data; rollback procedure tested; FR-07 deferred to follow-up |

## Dependencies

| Dependency | Type | Critical Path | Owner | Risk if Delayed | Contingency |
|---|---|---|---|---|---|
| triage-issue skill (tomzx/agents) | External | Yes | Project owner | Express flow cannot classify issues as eligible; express path is never entered | Ship express flow first (complexity absent = not eligible, safe degradation); enables phased rollout |
| create-implementation skill | Internal | Yes | Project owner | Express path cannot produce implementations; entire feature is blocked | Pre-validate with historical issues in Phase 6 before enabling production; may need to modify skill to tolerate missing artifacts |
| Historical issue PRs for testing | Internal | Yes (for Phase 6) | Project owner | Cannot verify quality parity (NFR-02); delays Phase 6 | Use synthetic test issues if historical PRs are unavailable; reduces confidence but unblocks verification |
| GitHub Actions runner availability | External | No | GitHub | Express path execution is delayed; timeout alerts fire | No mitigation (platform dependency); alert after 3 failures in 24h |
| LLM API availability | External | No | OpenAI/Anthropic | create-implementation step fails; failure path handles gracefully but repeated failures erode trust | Configure fallback model in `defaults.express.model`; failure path provides safe abort |
| Anti-spoofing verification | Internal | No (Phase 6) | Project owner | NFR-05 compliance gap; label manipulation risk unaddressed | Label compartmentalization provides inherent protection; audit trail available post-hoc |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| create-implementation skill fails without upstream planning artifacts | Medium | High | Phase 6 validation against historical issues; failure path (`llmaw:express-failed`) provides safe abort; may need to modify skill to tolerate missing artifacts |
| Classification accuracy is poor (too many false positives) | Medium | Medium | Configurable eligibility criteria; failure rate alert (20% threshold); can tighten `complexity_values` or `max_issue_body_chars` without code changes |
| Cross-repo deployment ordering causes issues | Low | Medium | Either order is safe per specification; complexity absent = not eligible; verify deployment order in Phase 7 |
| Token savings target not met (NFR-01) | Medium | Medium | Measure after first 5 runs; re-evaluate classification criteria or tighten scope if below 60% target |
| Code quality verification fails (NFR-02) — express-path PRs rejected for quality | Medium | High | Phase 6 quality comparison against historical PRs; if any of 3 test PRs is rejected, defer express path until quality gap is closed |
| Anti-spoofing / label manipulation (NFR-05) | Low | Medium | Label compartmentalization: `llmaw:express-eligible` auto-only vs. `llmaw:quick-implement` human-only; audit trail via issue timeline; Phase 6 verification |
| express-decision.md persists if issue re-processed through full pipeline | Low | Low | Document behavior in artifact; consumers must not assume artifact reflects current state after re-processing |
| Bus factor / single point of failure | Medium | Medium | Phase-6 verification uses 2 developers; cross-train on flow config and triage skill; document architecture decisions |
| Label namespace collisions with future additions | Low | Low | Document llmaw:\* namespace conventions; code review for new label additions |
| Express path consumes more tokens than expected due to express-decision.md | Low | Low | Defer artifact to post-hoc aggregation step if usage warrants |
| Terminal labels create stuck issues | Low | Low | By design (infinite loop prevention); human must intervene to retry; documented in Phase 5 rollback deliverables |
| Manual override rate exceeds 50% | Medium | Low | Review classification accuracy and eligibility criteria; adjust defaults.express.eligibility or triage prompt |

## Timeline (if capacity is known)

Assuming 2 developers at 50% allocation (Phase 6 requires both; all others single-developer with review support):

| Phase | Resource | Start | End | Notes |
|---|---|---|---|---|
| Phase 1: Triage Extension | 1 dev | Day 1 | Day 3 | Cross-repo PR; includes review iteration |
| Phase 2: Express Flow | 1 dev (+ 1 dev for labels/config) | Day 2 | Day 5 | Overlaps with Phase 1; prep work parallelizable |
| Phase 3: Decision Artifact | 1 dev | Day 5 | Day 5 | Single deliverable, deliverable in 1 day |
| **Buffer** | — | Day 6 | Day 6 | Integration testing across Phases 1-3; fix any issues |
| Phase 4: Telemetry Events | 1 dev | Day 6 | Day 7 | Can overlap with buffer |
| Phase 5: Alerting + Dry-Run | 1 dev | Day 8 | Day 9 | Blocked on Phase 4 telemetry events |
| **Buffer** | — | Day 10 | Day 10 | End-to-end integration testing; phase transition validation |
| Phase 6: Verification | 2 devs | Day 11 | Day 14 | 4 days for 3-5 historical test issues; quality comparison, CI verification, regression testing |
| **Buffer** | — | Day 15 | Day 15 | Verification failure remediation; re-test if needed |
| Phase 7: Rollout | 1 dev | Day 16 | Day 18 | Documentation + cross-repo deployment + monitoring setup + rollback procedure test |
