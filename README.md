# LLM Augmented Workflows

A complete automation framework for GitHub issue planning and implementation using Claude Code.
Convert GitHub issues into detailed implementation plans, review them through pull requests, and automatically implement approved plans.

## Features

- **Automated Issue Planning** - Automatically generates detailed implementation plans from GitHub issues
- **Two-Stage Review Process** - Plans are reviewed via PR before implementation begins
- **Automated Implementation** - Approved plans are automatically implemented
- **GitHub Actions Integration** - Fully integrated workflows for seamless automation
- **Claude Code Integration** - Uses `anthropics/claude-code-action` for intelligent code generation
- **Configurable Triggers** - Flexible label-based workflow triggering

## How It Works

```
GitHub Issue
     │
     ▼
[Plan Generated] → Plan PR Created
     │
     ▼
[Plan Reviewed & Merged]
     │
     ▼
[Auto-Labeled "plan-approved"]
     │
     ▼
[Implementation] → Implementation PR Created
     │
     ▼
[Review & Merge]
```

## Installation

### Prerequisites

1. GitHub repository with the [Claude GitHub App](https://github.com/apps/claude) installed
2. GitHub token with `repo`, `pull-request:write`, and `issues:write` permissions
3. Claude Code OAuth token

### Setup Options

Choose one of the following setup methods:

#### Option A: Use as Reusable Workflows (Recommended)

This option allows you to use these workflows without copying files to your repository. The workflows remain in this repository and are called from your repository via GitHub's reusable workflow feature.

1. **Make the workflows accessible**:
   - Star and fork this repository to your GitHub account, OR
   - Create a copy in your organization

2. **Copy the simplified wrapper workflows** to your repository:
   ```bash
   cp .github/wrappers/*.yml your-repo/.github/workflows/
   ```

3. **Copy additional files** to your repository:
   ```bash
   # Copy Claude commands and settings
   cp -r .claude your-repo/

   # Copy PR description template
   cp .github/pr-description-template.md your-repo/.github/
   ```

4. **Configure secrets** in your repository (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_AUTH_TOKEN` - Your Claude Code OAuth token, OR
   - `ANTHROPIC_API_KEY` - Your Anthropic API key
   (one of the above is required)

5. **Configure variables** in your repository (Settings → Secrets and variables → Actions → Variables):
   - `ANTHROPIC_BASE_URL` - (Optional) Custom base URL for the Anthropic API
   - `ANTHROPIC_MODEL` - (Optional) Specific model to use (e.g., `claude-sonnet-4-5-20250514`)

6. **Set up labels** in your repository:
   - `plan-needed` - Triggers plan generation
   - `plan-approved` - Triggers implementation

#### Option B: Copy to Your Own Repository

1. **Copy the workflow files** to your repository:
   ```bash
   # Copy workflows
   cp -r .github/workflows/*.yml your-repo/.github/workflows/

   # Copy Claude commands and settings
   cp -r .claude your-repo/

   # Copy PR description template
   cp .github/pr-description-template.md your-repo/.github/
   ```

2. **Configure secrets** in your repository settings (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_AUTH_TOKEN` - Your Claude Code OAuth token, OR
   - `ANTHROPIC_API_KEY` - Your Anthropic API key
   (one of the above is required)
   - `GITHUB_TOKEN` - Automatically provided by GitHub Actions (no setup needed)

3. **Configure variables** in your repository (Settings → Secrets and variables → Actions → Variables):
   - `ANTHROPIC_BASE_URL` - (Optional) Custom base URL for the Anthropic API
   - `ANTHROPIC_MODEL` - (Optional) Specific model to use (e.g., `claude-sonnet-4-5-20250514`)

4. **Set up labels** using one of these methods:
   - **Manual**: Create labels in your repository settings:
     - `plan-needed` - Triggers plan generation
     - `plan-approved` - Triggers implementation
   - **Automatic**: Run the `setup-labels.yml` workflow manually from the Actions tab

## Usage

### Basic Workflow

1. **Create an issue** describing what you want to implement
2. **Wait for plan generation** - A plan PR will be created automatically
3. **Review the plan** - Add comments, request changes, or approve
4. **Merge the plan PR** - This triggers implementation
5. **Review implementation** - An implementation PR will be created
6. **Merge the implementation PR** - Complete!

### Triggering Plan Generation

Plans are generated when:
- An issue is created with the `plan-needed` label, OR
- The `plan-needed` label is added to an existing issue

### Triggering Implementation

Implementation starts when:
- The plan PR is merged (auto-adds `plan-approved` label to the original issue)

## Configuration

Edit the workflow files to customize behavior:

| Option | Default | Description |
|--------|---------|-------------|
| `trigger_label` | `plan-needed` | Label that triggers plan generation |
| `approval_label` | `plan-approved` | Label that triggers implementation |
| `max_turns` | 100 | Maximum Claude Code turns per workflow |
| `allowed_tools` | *see below* | Tools Claude can use |

### Review Comments

Plan PRs support interactive review. When you comment on a plan PR:
- **Technical questions** - Claude responds with explanations
- **Change requests** - Claude updates the plan accordingly
- **Clarifications** - Claude provides additional details

This is handled automatically by the `claude-review.yml` workflow.

### Allowed Tools

By default, Claude can use:
- `Glob`, `Grep`, `Read`, `Write`, `Edit` - File operations
- `Bash(gh:*)` - GitHub CLI commands
- `Bash(git:*)` - Git commands
- `Bash(date:*)` - Date/time commands

## Project Structure

```
.github/
├── workflows/
│   ├── claude-plan.yml              # Issue → Plan workflow (reusable)
│   ├── claude-implement.yml          # Plan → Implementation workflow (reusable)
│   ├── claude-plan-merged.yml        # Auto-label on plan merge (reusable)
│   ├── claude-review.yml             # Respond to plan PR comments (reusable)
│   └── setup-labels.yml              # Label setup workflow
├── wrappers/
│   ├── issue-to-plan.yml             # Wrapper for plan generation
│   ├── plan-to-implement.yml         # Wrapper for implementation
│   ├── plan-merged.yml               # Wrapper for plan merge
│   └── plan-review.yml               # Wrapper for plan review comments
└── pr-description-template.md        # Implementation PR template

.claude/
├── commands/
│   ├── generate-plan.md              # Plan generation command
│   ├── implement-plan.md             # Implementation command
│   └── review-plan-comment.md        # Review response command
└── settings.local.json               # Claude settings

plans/                                # Generated plan files
```

## Customization

### Project Conventions

Edit `.claude/commands/generate-plan.md` and `implement-plan.md` to include:
- Code conventions (style, patterns)
- Testing guidelines
- Documentation standards

### PR Templates

Edit `.github/pr-description-template.md` to customize the implementation PR description format.

### Labels

Modify the label names in the workflow files to match your project's conventions.

## License

MIT License - see [LICENSE](LICENSE) for details.
