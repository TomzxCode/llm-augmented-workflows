#!/usr/bin/env python3
"""Execute the deterministic steps (``labels`` / ``shell``) of a matched rule.

The matched rule is passed as JSON in the ``MATCHED_RULE`` environment variable
(one Actions matrix entry). The subject (issue or PR) is taken from
``ISSUE_NUMBER`` / ``PR_NUMBER``. All GitHub mutations use the ``gh`` CLI with
``GH_TOKEN``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys

from .engine import compute_label_diff

log = logging.getLogger("run_steps")


def _gh(args: list[str], *, capture: bool = False) -> str:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=capture,
        text=True,
        check=True,
    )
    return proc.stdout if capture else ""


def _current_subject() -> tuple[int, str] | tuple[None, None]:
    issue = os.environ.get("ISSUE_NUMBER", "").strip()
    pr = os.environ.get("PR_NUMBER", "").strip()
    if issue:
        return int(issue), "issue"
    if pr:
        return int(pr), "pr"
    return None, None


def _current_labels(number: int, kind: str) -> list[str]:
    out = _gh(
        [kind, "view", str(number), "--json", "labels", "-q", ".labels[].name"],
        capture=True,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def _find_linked_issue() -> int | None:
    """Find an issue referenced in the PR title/body."""
    text = f"{os.environ.get('PR_TITLE', '')} {os.environ.get('PR_BODY', '')}"
    m = re.search(r"(?:closes|fixes|resolves|plan for issue)[^#\n]*#(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"#(\d+)", text)
    return int(m.group(1)) if m else None


def apply_labels(step: dict) -> None:
    body = step["labels"]
    add: list[str] = body.get("add", [])
    remove: list[str] = body.get("remove", [])
    target = body.get("target", "subject")

    if target == "linked-issue":
        number = _find_linked_issue()
        kind = "issue"
        if number is None:
            log.warning("labels step target=linked-issue but no linked issue found; skipping")
            return
    else:
        number, kind = _current_subject()

    if number is None:
        log.warning("labels step has no subject (ISSUE_NUMBER/PR_NUMBER unset); skipping")
        return

    current = _current_labels(number, kind)
    to_add, to_remove = compute_label_diff(current, add, remove)

    if to_add:
        _gh([kind, "edit", str(number), "--add-label", ",".join(to_add)])
    if to_remove:
        _gh([kind, "edit", str(number), "--remove-label", ",".join(to_remove)])
    log.info("labels %s #%d: +%s -%s", kind, number, to_add, to_remove)


def _resolve_script(script: str) -> str:
    """Resolve a script path against the main-pinned tooling root when set.

    The dispatcher snapshots ``.github/llmaw/`` (from main) into
    ``$LLMAW_TOOLING_ROOT`` before any rule switches the working tree to the
    per-issue branch, so scripts always run from main rather than whatever the
    branch carries. Falls back to the path as given (relative to cwd) when the
    var is unset or the snapshot does not contain the file.
    """
    root = os.environ.get("LLMAW_TOOLING_ROOT", "").strip()
    if root and not os.path.isabs(script):
        candidate = os.path.join(root, script)
        if os.path.exists(candidate):
            return candidate
    return script


def run_shell(step: dict) -> None:
    body = step["shell"]
    if isinstance(body, str):
        script, args = body, []
    elif isinstance(body, dict):
        script, args = body["run"], body.get("args") or []
    else:
        raise ValueError(f"invalid shell step body: {body!r}")
    script = _resolve_script(script)
    log.info("running shell step: %s %s", script, " ".join(args))
    subprocess.run(["bash", script, *args], check=True)


def main(phase: str = "pre") -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raw = os.environ.get("MATCHED_RULE")
    if not raw:
        log.error("MATCHED_RULE env var is not set")
        return 1

    rule = json.loads(raw)
    key = "deterministic" if phase == "pre" else "post_deterministic"
    for step in rule.get(key, []):
        if "labels" in step:
            apply_labels(step)
        elif "shell" in step:
            run_shell(step)
        else:
            log.warning("unknown deterministic step keys: %s", list(step))
    return 0


if __name__ == "__main__":
    sys.exit(main())
