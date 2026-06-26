# LLM Augmented Workflows

A complete automation framework for GitHub issue planning and implementation using opencode.
Convert GitHub issues into detailed implementation plans, review them through pull requests, and automatically implement approved plans.

## Features

- **Automated Issue Planning** - Automatically generates detailed implementation plans from GitHub issues
- **Two-Stage Review Process** - Plans are reviewed via PR before implementation begins
- **Automated Implementation** - Approved plans are automatically implemented
- **GitHub Actions Integration** - Fully integrated workflows for seamless automation
- **opencode Integration** - Uses `opencode run` to drive plan generation, implementation, and review
- **Configurable Skills Source** - Skills are loaded from any agents repository you choose
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

1. A target GitHub repository where the workflows will run
2. `GITHUB_TOKEN` with `repo`, `pull-request:write`, and `issues:write` permissions (provided automatically by GitHub Actions)
3. An agents repository (default: `tomzx/agents`) that provides the opencode skills `generate-plan`, `implement-plan`, and `review-plan-comment`

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
   # Copy the PR description template
   cp .github/pr-description-template.md your-repo/.github/
   ```

4. **Set up labels** in your repository:
   - `plan-needed` - Triggers plan generation
   - `plan-approved` - Triggers implementation

5. **(Optional) Configure variables** in your repository (Settings → Secrets and variables → Actions → Variables) to override the defaults:
   - `OPENCODE_MODEL` - opencode model id (default: `opencode/deepseek-v4-flash-free`)
   - `AGENTS_REPOSITORY` - skills repository as `owner/repo` (default: `tomzx/agents`)

#### Option B: Copy to Your Own Repository

1. **Copy the workflow files** to your repository:
   ```bash
   # Copy workflows
   cp -r .github/workflows/*.yml your-repo/.github/workflows/

   # Copy the PR description template
   cp .github/pr-description-template.md your-repo/.github/
   ```

2. **Set up labels** using one of these methods:
   - **Manual**: Create labels in your repository settings:
     - `plan-needed` - Triggers plan generation
     - `plan-approved` - Triggers implementation
   - **Automatic**: Run the `setup-labels.yml` workflow manually from the Actions tab

3. **(Optional) Configure variables** as described in Option A.

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

Each workflow resolves its model and skills repository with this priority:

1. **Workflow input** (`model`, `agents-repository`) - set when triggering manually or calling as a reusable workflow
2. **Repository variable** (`OPENCODE_MODEL`, `AGENTS_REPOSITORY`) - set under Settings → Secrets and variables → Actions → Variables
3. **Hardcoded default** - `opencode/deepseek-v4-flash-free` and `tomzx/agents`

| Option | Default | Description |
|--------|---------|-------------|
| `model` | `opencode/deepseek-v4-flash-free` | opencode model id (provider/model) |
| `agents-repository` | `tomzx/agents` | Repository providing the plan/implement/review skills |
| `trigger_label` | `plan-needed` | Label that triggers plan generation |
| `approval_label` | `plan-approved` | Label that triggers implementation |

### Skills Source

The `generate-plan`, `implement-plan`, and `review-plan-comment` skills are cloned from the configured `agents-repository` at runtime and linked into `~/.opencode/skills`. Point `agents-repository` at any fork or alternative that provides equivalent skills.

### Review Comments

Plan PRs support interactive review. When you comment on a plan PR:
- **Technical questions** - opencode responds with explanations
- **Change requests** - opencode updates the plan accordingly
- **Clarifications** - opencode provides additional details

This is handled automatically by the `review.yml` workflow.

## Project Structure

```
.github/
├ workflows/
│   ├── plan.yml                       # Issue → Plan workflow (reusable)
│   ├── implement.yml                  # Plan → Implementation workflow (reusable)
│   ├── plan-merged.yml                # Auto-label on plan merge (reusable)
│   ├── review.yml                     # Respond to plan PR comments (reusable)
│   └── setup-labels.yml               # Label setup workflow
├ wrappers/
│   ├── plan.yml                       # Wrapper for plan generation
│   ├── implement.yml                  # Wrapper for implementation
│   ├── plan-merged.yml                # Wrapper for plan merge
│   ├── review.yml                     # Wrapper for plan review comments
│   └── setup-labels.yml               # Wrapper for label setup
└── pr-description-template.md         # Implementation PR template

plans/                                 # Generated plan files
```

## Customization

### Skills

The plan, implementation, and review behavior is defined by the skills in your configured `agents-repository` (default `tomzx/agents`). Fork that repository and point `agents-repository` at your fork to customize the prompts and workflow logic.

### PR Templates

Edit `.github/pr-description-template.md` to customize the implementation PR description format.

### Labels

Modify the label names in the workflow files to match your project's conventions.

## License

MIT License - see [LICENSE](LICENSE) for details.
