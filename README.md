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

### Setup

1. **Copy workflow files** to your repository:
   ```bash
   cp -r .github/workflows/* your-repo/.github/workflows/
   cp -r .claude your-repo/
   ```

2. **Configure secrets** in your repository settings:
   - `CLAUDE_CODE_OAUTH_TOKEN` - Your Claude Code OAuth token
   - `ANTHROPIC_API_KEY` (optional) - If using Anthropic API directly

3. **Set up labels** - Either manually create the labels or run `setup-labels.yml`:
   - `plan-needed` - Triggers plan generation
   - `plan-approved` - Triggers implementation

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
│   ├── claude-plan.yml              # Issue → Plan workflow
│   ├── claude-implement.yml          # Plan → Implementation workflow
│   ├── claude-plan-merged.yml        # Auto-label on plan merge
│   └── setup-labels.yml              # Label setup workflow
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
