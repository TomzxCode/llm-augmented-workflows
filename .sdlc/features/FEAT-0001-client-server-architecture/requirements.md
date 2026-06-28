---
issue: "#16"
title: "Client/Server architecture"
status: approved
---

# Requirements: Client/Server architecture

## Overview

The current automation engine runs inside GitHub Actions runners as a stateless CLI invoked per-event via workflows. This requires a full repository checkout on every execution, limits runtime state between events, and ties execution to GitHub runner availability. This feature replaces the GitHub Actions execution model with a hosted server that receives GitHub webhook events, maintains persistent agent state, and orchestrates agent execution on the server side. Repos that adopt this architecture no longer need to install and configure the engine via GitHub Actions workflows.

## Stakeholders

| Stakeholder | Interest |
|---|---|
| Project users / adopters | Want reliable automation that does not depend on GitHub Actions quotas, checkout latency, or workflow configuration |
| Project maintainer | Needs centralized observability, control over the execution environment, and ability to update the engine without coordinating per-repo workflow updates |
| Downstream repo owners | Want to enable automation by configuring a webhook URL and a token, not by writing and maintaining GitHub Actions workflows |

## Functional Requirements

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | Must | The server shall expose an HTTP endpoint that accepts GitHub webhook events (push, pull_request, issue_comment, issues) and dispatches them to the agent pipeline |
| FR-02 | Must | The server shall maintain persistent session state for each repository so that agent state (conversation history, context, step progress) survives between webhook events |
| FR-03 | Must | The server shall support registration of webhook targets (repositories) with a unique secret token for payload verification |
| FR-04 | Must | The server shall execute agent logic (prompt construction, LLM calls, action dispatch) on the server side, removing the need for a GitHub Actions runner to do so |
| FR-05 | Must | The server shall dispatch actions back to GitHub (comment on issues/PRs, create commits, update labels) using the GitHub API, authenticated per-repository |
| FR-06 | Should | The server shall provide a health-check endpoint (GET /health) returning server status |
| FR-07 | Should | The server shall support graceful shutdown: finish in-flight agent executions before terminating |
| FR-08 | Should | The server shall log all webhook events, agent decisions, and outbound GitHub API calls in a structured format suitable for debugging and observability |
| FR-09 | May | The server shall expose a REST API for administrators to view registered repositories, active sessions, and execution logs |
| FR-10 | May | The server shall support running multiple agent versions simultaneously (canary deployments) |

## Non-Functional Requirements

| ID | Requirement | Category |
|---|---|---|
| NFR-01 | The server shall verify webhook payload signatures using HMAC-SHA256 before processing any event | Security |
| NFR-02 | The server shall authenticate all its outbound GitHub API calls using per-repository installation tokens or PATs, never a shared credential | Security |
| NFR-03 | The server shall start processing a webhook event within 5 seconds of receipt under normal load (excluding LLM inference time) | Performance |
| NFR-04 | The server shall support at least 10 concurrently active repositories without degradation | Performance |
| NFR-05 | The server shall recover from a crash without losing committed session state (at-most-once loss of in-flight agent steps is acceptable) | Availability |
| NFR-06 | The server shall limit retries on transient errors (e.g., GitHub API rate limits) to at most 3 attempts with exponential backoff | Reliability |
| NFR-07 | The server shall be deployable as a single Docker container with no external runtime dependencies beyond the LLM API and GitHub API | Operability |

## Constraints

- Must use the same agent/prompt logic as the existing GitHub Actions engine (no separate agent implementation)
- Must integrate with the existing action dispatching system used by the CLI harness
- Must not require changes to how downstream repos write their issue/PR descriptions — the agent behavior should be identical from the user's perspective
- Must run on commodity cloud infrastructure or a single VM (no Kubernetes requirement)

## Acceptance Criteria

- [ ] **FR-01**
    - **Given** a running server instance
    - **When** a push event payload is POSTed to the webhook endpoint with a valid HMAC signature
    - **Then** the server responds with HTTP 200 and the event is logged

- [ ] **FR-01** (invalid signature)
    - **Given** a running server instance
    - **When** a push event is POSTed with a missing or incorrect HMAC signature
    - **Then** the server responds with HTTP 401 and discards the payload

- [ ] **FR-02**
    - **Given** a running server with an active session for repo "my-org/my-repo"
    - **When** two sequential issue_comment events arrive for the same issue
    - **Then** the second agent invocation has access to the conversation history from the first invocation

- [ ] **FR-02** (new repo)
    - **Given** a running server
    - **When** the first webhook event arrives for a previously unregistered repository
    - **Then** the server creates a new session and processes the event without error

- [ ] **FR-03**
    - **Given** the server registration API
    - **When** an admin registers "my-org/my-repo" with a secret token
    - **Then** subsequent webhook events signed with that token are accepted and others are rejected

- [ ] **FR-04**
    - **Given** a registered repository with a pull_request.opened event
    - **When** the server processes the event
    - **Then** the agent produces a PR review comment identical to what the CLI-based engine would produce

- [ ] **FR-05**
    - **Given** an agent execution that decides to post an issue comment
    - **When** the server dispatches the action via the GitHub API
    - **Then** the comment appears on the correct issue within the repo

- [ ] **FR-05** (API error)
    - **Given** an agent action that requires a GitHub API call
    - **When** the API returns a 403 or rate-limit error
    - **Then** the server retries up to 3 times with exponential backoff and logs the failure if all retries are exhausted

- [ ] **NFR-01**
    - **Given** a server configured with a shared secret
    - **When** a webhook payload signed with that secret is received
    - **Then** the server processes it
    - **When** a webhook payload with a forged or missing signature is received
    - **Then** the server rejects it with HTTP 401

- [ ] **NFR-05**
    - **Given** a server with committed session state for a repository
    - **When** the server process is killed and restarted
    - **Then** webhook events for that repository resume processing with the prior session state restored

## Conflicts

None identified yet.

## Open Questions

1. Should the server support multiple deployment models (single-tenant per repo vs. multi-tenant across repos) from day one, or start single-tenant?
2. How should the server handle GitHub App installation lifecycle events (installed, uninstalled) — automatically register/unregister the target repo?
3. Should session state be persisted to disk or to an external store (Redis, SQLite, Postgres)?
4. How are downstream repo owners expected to deploy and manage their own server instance, or is this intended as a central service operated by the project maintainer?
5. What is the expected event volume per repository (e.g., events per hour) to inform throughput and scaling targets?
