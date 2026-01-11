# GitHub Workflow Implementation: Claude Code Action for Planning & Implementation

## Summary

Implement a two-stage GitHub workflow system using `anthropics/claude-code-action`:
1. **Issue → Plan PR**: Auto-generate implementation plans from issues
2. **Plan Approved → Implementation PR**: Auto-implement approved plans

## Critical Files to Create

| File | Purpose |
|------|---------|
| `.github/workflows/claude-plan.yml` | Issue→Plan workflow (entry point) |
| `.claude/commands/generate-plan.md` | Plan generation prompt/slash command |
| `.github/workflows/claude-implement.yml` | Plan→Implementation workflow |
| `.claude/commands/implement-plan.md` | Implementation prompt/slash command |
| `CLAUDE.md` | Project-specific Claude instructions |
| `.github/pr-description-template.md` | Template for implementation PRs |
| `.github/workflows/claude-review.yml` | Optional: PR review response workflow |
| `.github/workflows/claude-plan-merged.yml` | Adds label to issue when plan PR is merged |

## Implementation Steps

### Step 1: Create directory structure
```bash
mkdir -p .github/workflows
mkdir -p .claude/commands
mkdir -p plans
```

### Step 2: Create `.github/workflows/claude-plan.yml`
- Trigger: `issues: [opened]`
- Conditional label filtering (configurable - if empty, trigger on all issues)
- Checkout code at default branch with `fetch-depth: 1`
- Run Claude Code with `/generate-plan` slash command
- Prompt includes: REPO, ISSUE_NUMBER, ISSUE_TITLE, ISSUE_BODY, ISSUE_AUTHOR
- Claude should:
  - Read issue via `gh issue view`
  - Explore codebase (Glob, Grep, Read)
  - Assess feasibility
  - If infeasible: Comment on issue explaining why
  - If feasible: Create `plans/{issue-number}.md` and PR
- PR naming: "Plan for issue #{issue-number}"
- Branch: `plan/issue-{issue-number}-{timestamp}`

### Step 3: Create `.claude/commands/generate-plan.md`
Slash command with detailed prompt:
1. Read issue details (including comments)
2. Explore codebase for context
3. Feasibility assessment
4. If infeasible → comment and stop
5. If feasible → generate plan with sections:
   - Issue Summary
   - Feasibility Assessment (Status, Complexity, Effort)
   - Proposed Solution (Overview, Implementation Steps, Dependencies, Risks)
   - Alternatives Considered
   - References
6. Create plan PR with link to issue

### Step 4: Create `.github/workflows/claude-implement.yml`
- Trigger: `issues: [labeled]`
- Check if label is "plan-approved" (configurable)
- Checkout code at default branch with `fetch-depth: 1`
- Run Claude Code with `/implement-plan` slash command
- Prompt includes: REPO, ISSUE_NUMBER
- Claude should:
  - Check if `plans/{issue-number}.md` exists
  - If plan missing: Comment on issue explaining plan is missing, remove "plan-approved" label
  - If plan exists: Read it, get context from issue and plan PR, implement step-by-step
  - Create PR with template-based description
  - Generate an appropriate PR title based on what was implemented (LLM-generated, not "Implementation for issue #{issue-number}")
- Branch: `impl/issue-{issue-number}-{timestamp}`

### Step 5: Create `.claude/commands/implement-plan.md`
Slash command with detailed prompt:
1. Read plan file
2. Explore existing code patterns
3. Get issue and plan PR context via `gh`
4. Implement following plan steps
5. Quality checks (conventions, error handling, testing)
6. Create PR using template

### Step 6: Create `.github/pr-description-template.md`
Template with sections:
- Related Links (Issue, Plan PR, Plan File)
- Overview
- Changes Made (Files Modified/Added/Deleted)
- Implementation Notes
- Testing
- Checklist

### Step 7: Create `CLAUDE.md`
Project-specific instructions:
- Workflow context explanation
- Guidelines for planning, implementing, and reviewing
- Code conventions placeholder
- Testing guidelines placeholder
- Documentation standards placeholder

### Step 8: Create `.github/workflows/claude-plan-merged.yml`
- Trigger: `pull_request: [closed]` with `merged: true`
- Check if PR is a plan PR (branch prefix `plan/`)
- Extract issue number from PR title "Plan for issue #{N}" or branch name
- Add "plan-approved" label to the original issue via `gh issue edit`
- This triggers the implementation workflow automatically

### Step 9: Optional PR Review Workflow `.github/workflows/claude-review.yml`
- Trigger: `pull_request_review_comment: [created]`, `issue_comment: [created]`
- Filter for plan PRs (branch prefix `plan/`)
- Prompt: Analyze comment and respond
- Claude uses judgment: update plan vs discuss only
- Response types:
  - Plan update request → Edit plan file, commit, respond
  - Question → Answer in comment
  - Discussion → Engage thoughtfully

### Step 9: Create `.claude/commands/review-plan-comment.md`
Slash command defining review response behavior:
1. Read plan file
2. Analyze comment intent
3. Determine response type (update/discuss/answer)
4. Execute appropriate action

## Configuration Options (Workflow Inputs)

| Option | Default | Description |
|--------|---------|-------------|
| `trigger_labels` | `[]` | Empty = all issues; specify labels for conditional trigger |
| `approval_label` | `plan-approved` | Label to trigger implementation |
| `plan_branch_prefix` | `plan/` | Branch prefix for plan PRs |
| `impl_branch_prefix` | `impl/` | Branch prefix for implementation PRs |

## GitHub Setup Requirements

1. **Install Claude GitHub App**: https://github.com/apps/claude
2. **Required Secrets**:
   - `ANTHROPIC_API_KEY` - Claude API key
   - `CLAUDE_CODE_OAUTH_TOKEN` - OAuth token for Claude Code Action
3. **Required Permissions** (in workflow files):
   - `contents: write`
   - `pull-requests: write`
   - `issues: write`
   - `id-token: write`

## Flow Diagram

```
Issue Created
    ↓
claude-plan.yml triggered
    ↓
Check labels (if configured)
    ↓
Claude: Read issue, explore codebase, assess feasibility
    ├─→ Not feasible → Comment on issue → STOP
    └─→ Feasible → Create plans/{N}.md → Create plan PR
          ↓
    Developers review plan PR
          ↓
    Comments → claude-review.yml responds (optional)
          ↓
    Plan approved → Merge plan PR
          ↓
claude-plan-merged.yml triggered
    ↓
Add "plan-approved" label to original issue
          ↓
claude-implement.yml triggered
    ↓
Claude: Read plan, implement, create PR (LLM-generated title)
    ↓
Implementation PR with template description
    ↓
Developers review and merge
```

## Verification

1. Create a test issue
2. Verify plan workflow triggers (check Actions tab)
3. Verify plan PR created with correct naming and plan file
4. Merge the plan PR
5. Verify "plan-approved" label is added to original issue automatically
6. Verify implementation workflow triggers
7. Verify implementation PR created with:
   - LLM-generated title (not "Implementation for issue #{N}")
   - Template description with links to issue and plan PR

## Edge Cases Handled

- **Infeasible requests**: Claude comments on issue explaining why
- **Missing plan file**: When "plan-approved" label added but no plan exists, Claude comments on issue explaining plan is missing and removes the label
- **Failed implementation**: Claude attempts recovery or comments with explanation
- **Plan updates after implementation**: Implementation uses plan as-is when label added
- **Race conditions**: Can add `concurrency` setting to workflows
- **Large repos**: Use `fetch-depth: 1` for shallow clone (most common case)

## Sources

- [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action)
- [Claude Code GitHub Actions Docs](https://code.claude.com/docs/en/github-actions)
- [Setup Guide](https://github.com/anthropics/claude-code-action/blob/main/docs/setup.md)
- [Usage Guide](https://github.com/anthropics/claude-code-action/blob/main/docs/usage.md)
