#!/usr/bin/env bash
# Deterministic transition: close the issue linked to a merged implementation PR.
# Expects PR_TITLE and PR_BODY in the environment, plus GH_TOKEN for `gh`.
set -euo pipefail

text="${PR_TITLE:-} ${PR_BODY:-}"

# Prefer an explicit keyword reference, then fall back to any #<number>.
issue="$(printf '%s\n' "$text" \
  | grep -oiE '(closes|fixes|resolves|plan for issue)[^#]*#[0-9]+' \
  | grep -oE '#[0-9]+' | head -n1 | tr -d '#' || true)"

if [ -z "${issue:-}" ]; then
  issue="$(printf '%s\n' "$text" | grep -oE '#[0-9]+' | head -n1 | tr -d '#' || true)"
fi

if [ -z "${issue:-}" ]; then
  echo "No linked issue found in PR; nothing to close."
  exit 0
fi

echo "Closing issue #$issue as the linked PR was merged."
gh issue close "$issue" --comment "Closing as the linked PR was merged."
