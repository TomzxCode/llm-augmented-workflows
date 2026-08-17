#!/usr/bin/env python3
"""Execute the deterministic steps (``labels`` / ``shell``) of a matched rule.

The matched rule is passed as JSON in the ``MATCHED_RULE`` environment variable
(one Actions matrix entry). The subject (issue or PR) is taken from
``ISSUE_NUMBER`` / ``PR_NUMBER``. Tracker mutations go through a
:class:`~llm_augmented_workflows.trackers.base.TrackerClient` (``gh`` for
GitHub, per-subject YAML files for local runs).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

from .engine import ConfigError, compute_label_diff, load_flows
from .trackers import load_tracker
from .trackers.base import SubjectRef, TrackerClient

log = logging.getLogger("run_steps")

DEFAULT_FLOWS_FILE = ".github/llmaw/flows.yml"


def current_subject_ref() -> SubjectRef | None:
    """The subject of this dispatch, from the dispatcher/trigger env contract."""
    issue = os.environ.get("ISSUE_NUMBER", "").strip()
    pr = os.environ.get("PR_NUMBER", "").strip()
    if issue:
        return SubjectRef("issue", issue)
    if pr:
        return SubjectRef("pull_request", pr)
    return None


def build_client() -> TrackerClient:
    """Construct the tracker client from ``flows.yml`` (``tracker:`` block)."""
    flows_raw = load_flows(os.environ.get("FLOWS_FILE", DEFAULT_FLOWS_FILE))
    return load_tracker(flows_raw)


def apply_labels(step: dict, client: TrackerClient) -> None:
    body = step["labels"]
    add: list[str] = body.get("add", [])
    remove: list[str] = body.get("remove", [])
    target = body.get("target", "subject")

    ref: SubjectRef | None = None
    if target == "linked-issue":
        current = current_subject_ref()
        ref = client.find_linked_subject(current) if current else None
        if ref is None:
            log.warning("labels step target=linked-issue but no linked issue found; skipping")
            return
    else:
        ref = current_subject_ref()

    if ref is None:
        log.warning("labels step has no subject (ISSUE_NUMBER/PR_NUMBER unset); skipping")
        return

    current_labels = client.get_labels(ref)
    to_add, to_remove = compute_label_diff(current_labels, add, remove)

    if to_add:
        client.add_labels(ref, to_add)
    if to_remove:
        client.remove_labels(ref, to_remove)
    log.info("labels %s %s#%s: +%s -%s", client.name, ref.kind, ref.id, to_add, to_remove)


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

    try:
        client = build_client()
    except (ConfigError, ValueError) as exc:
        log.error("cannot construct tracker client: %s", exc)
        return 1

    rule = json.loads(raw)
    key = "deterministic" if phase == "pre" else "post_deterministic"
    for step in rule.get(key, []):
        if "labels" in step:
            apply_labels(step, client)
        elif "shell" in step:
            run_shell(step)
        else:
            log.warning("unknown deterministic step keys: %s", list(step))
    return 0


if __name__ == "__main__":
    sys.exit(main())
