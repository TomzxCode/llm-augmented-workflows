# Vocabulary

## Domain Terms

| Term | Definition |
|---|---|
| Flow | A named group of rules in `flows.yml`; grouping is organizational and does not affect routing (routing is flat across all flows). |
| Rule | An event-matched entry with a unique `id`, a `when` matcher, and an ordered `run` pipeline of steps. One Actions matrix entry per matched rule. |
| Step | One item in a rule's `run` list, discriminated by exactly one key (`labels`, `shell`, `skill`, `prompt`, `on_outcome`). |
| Deterministic step | A `labels` or `shell` step: token-free, no LLM, run directly by the engine via `gh` or `bash`. |
| Agent step | A `skill` or `prompt` step that runs `opencode` and costs tokens. At most one agent step per rule. |
| `on_outcome` | A post-agent step that switches on the agent's emitted `verdict` and applies a labels/close/comment action. |
| Transient trigger label | A `llmaw:create-<step>` / `llmaw:review-<step>` label consumed on entry by its matching rule; re-addable to drive revise loops. |
| Durable milestone label | A `*-approved` / `shipped` / `bug-fixed` / `finished` label that accumulates as an audit record, is never removed, and is never used as a trigger (a durable label cannot be re-added). |
| Subject | The issue or PR a rule acts on (from `ISSUE_NUMBER` / `PR_NUMBER`). |
| Linked issue | The issue referenced by `#N` (or `closes|fixes|resolves|plan for issue #N`) in a PR title/body; the target of `target: linked-issue` label steps. |
| Execution mode | How a dispatch behaves after a rule's pipeline: `event-driven` (one job per phase) or `continuous` (chain rules in one job until a terminal condition). |
| Continuous chaining | In continuous mode, re-reading the issue's labels after a rule runs and matching the next rule against newly-added labels, looping until `llmaw:needs-human`, no new label, no matching rule, or the iteration cap. |
| Agents repository | The external repo (default `tomzx/agents`) cloned at runtime to source opencode skills; its `skills/` and `AGENTS.md` are symlinked into `~/.opencode`. |
| Tooling root | `$LLMAW_TOOLING_ROOT`: a snapshot of `.github/llmaw/` from `main` taken before any rule switches to the per-issue branch, so the flow config and scripts always run from main. |

## Technical Terms

| Term | Definition |
|---|---|
| `llmaw` | The console script (`llmaw route | run-rule | run-steps | apply-outcome | sync-labels`) installed from this package. |
| opencode | The agent runner invoked as `opencode run --model <id> --dangerously-skip-permissions --command <skill>` (skill step) or with a prompt file's text (prompt step). |
| `--dangerously-skip-permissions` | opencode flag mapped from `permissions: skip`; what the workflows pass so the agent runs unattended. |
| App token | A GitHub App installation token minted by `actions/create-github-app-token@v3`; used for chaining mutations because events from the default `GITHUB_TOKEN` never trigger downstream workflows (anti-recursion). |
| `$OUTCOME_YAML` | File path set by the dispatcher where the skill writes `{verdict, reason}` as its final action; read by `apply_outcome` to select the action. |
| Verdict | The skill's domain decision string (e.g. `approved`, `rejected`, `changes-requested`, `needs-info`, `reproduced`) that `on_outcome` cases switch on. |
| `post_reason` | An `on_outcome` action flag that posts the outcome's `reason` instead of the action's hardcoded `comment`. |
| Outcome continuation | When a rule expects an outcome but the skill wrote none or omitted `reason`, the engine resumes the opencode session once (`opencode run --continue`) to request a complete `$OUTCOME_YAML`. |
| `when` matcher | Event matcher whose fields (`event`, `action`, `label`, `merged`, `branch_prefix`, `body_contains`) are ANDed; unspecified fields are wildcards. |
| Label diff | The idempotent add/remove computation: add only labels absent, remove only labels present, so operations never error on already-present/absent labels. |
| `migrate_from` | A declared label's list of predecessor names to rename onto the current name; GitHub moves carrying issues on rename, preserving history. |
| Matrix | The JSON array of matched rules emitted by `llmaw route`, consumed by the Actions matrix to spawn one isolated job per matched rule. |
| `.llmaw/` | The directory where the engine repo is checked out on the worker; `uv run --project .llmaw llmaw ...` runs the engine. |

## Acronyms and Abbreviations

| Abbreviation | Expansion |
|---|---|
| LLM | Large Language Model |
| LLM-AW / llmaw | LLM-Augmented Workflows (this project and its CLI) |
| SDLC | Software Development Lifecycle |
| PR | Pull Request |
| CI | Continuous Integration |
| GHA | GitHub Actions |
| CLI | Command-Line Interface |
| NFR | Non-Functional Requirement |
| ADR | Architecture Decision Record |
| PEM | Privacy-Enhanced Mail (the GitHub App private key format) |
