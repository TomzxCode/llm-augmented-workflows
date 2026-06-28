---
issue: "#17"
title: "Implement directly from issue"
status: draft
---

# Implementation Plan: Implement directly from issue

## Goal

Add a lightweight express path that routes eligible issues directly from triage to implementation, skipping intermediate planning phases while producing a minimal traceability artifact. The express path operates alongside the existing feature and bugfix flows without modifying them.

## Phases

### Phase 1: Triage-Issue Skill Extension

**Goal:** The `triage-issue` skill emits an optional `complexity` field in its verdict YAML.
**Effort:** 2 person-days
**Depends on:** None

**Deliverables:**
- [ ] Add `complexity: low | medium | high` optional field to triage-issue skill's `$OUTCOME_YAML` output
- [ ] Add complexity assessment logic to the triage prompt (classify based on scope, cross-cutting concerns, file count, dependencies)
- [ ] When complexity is absent, consumers treat issue as "not express-eligible" (backward compatible)

### Phase 2: Express Flow Configuration

**Goal:** New `express` flow in `flows.yml` with two rules, config block, and on_outcome handlers.
**Effort:** 3 person-days
**Depends on:** Phase 1 (either order safe per spec, but logical dependency exists)

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

**Deliverables:**
- [ ] Implement `express-decision.md` artifact with schema_version, trigger, complexity, reason, implemented_at, outcome, pr_url
- [ ] Write artifact on implementation success or failure
- [ ] Ensure artifact follows `.sdlc/features/FEAT-NNNN-<slug>/express-decision.md` path convention

### Phase 4: Telemetry and Observability

**Goal:** All metrics, events, logging, and alerting defined in the telemetry and observability plans are implemented.
**Effort:** 3 person-days
**Depends on:** Phases 1, 2

**Deliverables:**
- [ ] Emit structured `TELEMETRY_EVENT` log lines from `flows.yml` on_outcome handlers for: `classification_comment_posted`, `routing_decision_made`, `express_override_used`, `express_label_removed`
- [ ] Add telemetry event emission for `implementation_started`, `implementation_completed`, `implementation_failed` from the express flow and `create-implementation` skill outcome
- [ ] Add `workflow_step_failed` event emission from failure handlers in flows.yml
- [ ] Expose `token_input`, `token_output`, `duration_seconds` in `create-implementation` outcome YAML
- [ ] Implement express flow match logging (INFO level) and failure logging (ERROR level)
- [ ] Implement label state transition logging for all `llmaw:*` labels
- [ ] Add post-hoc alert aggregation logic (weekly summary computation of failure rates, token efficiency, timeout events)
- [ ] Implement periodic dry-run test workflow for express path health check

### Phase 5: Verification and Hardening

**Goal:** Verify the express path works correctly against historical issues and meets NFR targets.
**Effort:** 3 person-days
**Depends on:** Phases 1, 2, 3, 4

**Deliverables:**
- [ ] Run `create-implementation` skill against 3-5 historical issues with known PRs
- [ ] Compare express-path output against actual implementations for quality parity
- [ ] Verify token consumption stays below 60% of full-pipeline baseline (NFR-01)
- [ ] Verify CI checks pass on generated PRs (NFR-02)
- [ ] Verify that ineligible issues correctly fall through to the full pipeline
- [ ] Verify classification accuracy (false-positive rate below 20%)
- [ ] Verify label state machine transitions (happy path, failure, override, removal)
- [ ] Verify backward compatibility: existing feature and bugfix flows are unaffected

### Phase 6: Documentation and Rollout

**Goal:** Express path is documented, deployable, and monitored in production.
**Effort:** 2 person-days
**Depends on:** Phase 5

**Deliverables:**
- [ ] Update flows.yml documentation with express path rules and config
- [ ] Update README or project docs with express path overview
- [ ] Coordinate cross-repo deployment: update `triage-issue` skill in `tomzx/agents` first (or verify safe ordering)
- [ ] Enable express path in production configuration
- [ ] Set up initial monitoring (label-based queries, weekly alert review)
- [ ] Record baseline token consumption from first 5 express-path runs

## Milestones

| Milestone | Phase | Success Criteria |
|---|---|---|
| M1: Triage emits complexity | Phase 1 | triage-issue skill's `$OUTCOME_YAML` contains `complexity` field on eligible issues |
| M2: Express flow operational | Phase 2 | A test issue labeled `llmaw:quick-implement` triggers the express flow and reaches `create-implementation` |
| M3: Artifact trail complete | Phase 3 | `express-decision.md` is written on both success and failure of express-path issues |
| M4: Observability live | Phase 4 | Structured log lines appear in GITHUB_STEP_SUMMARY for express-path events; token consumption is captured |
| M5: Quality verified | Phase 5 | 3/3 historical test issues produce code quality equivalent to original implementations; token consumption is below 60% of full pipeline |
| M6: Production ready | Phase 6 | Express path is enabled; monitoring queries return data; deployment ordering is verified safe |

## Dependencies

| Dependency | Type | Owner | Risk if Delayed |
|---|---|---|---|
| triage-issue skill (tomzx/agents) | External | Project owner | Express flow cannot classify issues as eligible; express path is never entered |
| create-implementation skill | Internal | Project owner | Express path cannot produce implementations; entire feature is blocked |
| Historical issue PRs for testing | Internal | Project owner | Cannot verify quality parity (NFR-02); delays Phase 5 |
| GitHub Actions runner availability | External | GitHub | Express path execution is delayed; timeout alerts fire |
| LLM API availability | External | OpenAI/Anthropic | create-implementation step fails; failure path handles gracefully but repeated failures erode trust |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| create-implementation skill fails without upstream planning artifacts | Medium | High | Phase 5 validation against historical issues; failure path (`llmaw:express-failed`) provides safe abort; may need to modify skill to tolerate missing artifacts |
| Classification accuracy is poor (too many false positives) | Medium | Medium | Configurable eligibility criteria; failure rate alert (20% threshold); can tighten `complexity_values` or `max_issue_body_chars` without code changes |
| Cross-repo deployment ordering causes issues | Low | Medium | Either order is safe per specification; complexity absent = not eligible; verify deployment order in Phase 6 |
| Token savings target not met | Medium | Medium | Measure after first 5 runs; re-evaluate classification criteria or tighten scope if below 60% target |
| Label namespace collisions with future additions | Low | Low | Document llmaw:* namespace conventions; code review for new label additions |
| Express path consumes more tokens than expected due to express-decision.md | Low | Low | Defer artifact to post-hoc aggregation step if usage warrants |
| Terminal labels create stuck issues | Low | Low | By design (infinite loop prevention); human must intervene to retry |
| Manual override rate exceeds 50% | Medium | Low | Review classification accuracy and eligibility criteria; adjust defaults.express.eligibility or triage prompt |

## Timeline (if capacity is known)

Assuming 1-2 developers with 50% allocation:

| Phase | Start | End | Notes |
|---|---|---|---|
| Phase 1: Triage Extension | Day 1 | Day 2 | Can parallelize with Phase 2 prep |
| Phase 2: Express Flow | Day 2 | Day 4 | Overlaps with Phase 1 |
| Phase 3: Decision Artifact | Day 4 | Day 4 | Single deliverable, 1 day |
| Phase 4: Observability | Day 4 | Day 6 | Can parallelize with Phase 3 |
| Phase 5: Verification | Day 7 | Day 9 | Blocked until Phases 1-4 complete |
| Phase 6: Rollout | Day 10 | Day 11 | Documentation + deployment |
