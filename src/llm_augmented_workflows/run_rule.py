#!/usr/bin/env python3
"""Execute matched rules end to end as a single pipeline.

For each matched rule, runs its whole ``run`` in this one process:
pre deterministic (``labels``/``shell``) -> agent (``opencode``) -> post
deterministic -> ``on_outcome``. Replaces the former per-step GitHub Actions
steps (run-steps / run-agent / apply-outcome) with one driver command.

Reads the matched rules from ``MATCHED_FILE`` (a JSON list) or a single rule
from ``MATCHED_RULE``. GitHub mutations use ``gh`` via ``run_steps``; the agent
runs via ``opencode`` (installed by the workflow when any rule has an agent).
``opencode`` and ``gh`` inherit this process's environment, so the workflow
sets ``GH_TOKEN`` / ``ISSUE_NUMBER`` / ``PR_NUMBER`` / etc. on this step.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from . import run_steps
from .apply_outcome import apply

log = logging.getLogger("run_rule")


def _read_rules() -> list[dict]:
    matched_file = os.environ.get("MATCHED_FILE")
    if matched_file and Path(matched_file).exists():
        return json.loads(Path(matched_file).read_text())
    raw = os.environ.get("MATCHED_RULE")
    return [json.loads(raw)] if raw else []


def _run_deterministic(steps: list[dict]) -> None:
    for step in steps:
        if "labels" in step:
            run_steps.apply_labels(step)
        elif "shell" in step:
            run_steps.run_shell(step)
        else:
            log.warning("unknown step keys: %s", list(step))


def _run_agent(agent: dict) -> None:
    cmd = ["opencode", "run", "--model", agent["model"], "--dangerously-skip-permissions"]
    if agent["kind"] == "skill":
        cmd += ["--command", agent["ref"]]
    else:
        cmd += [Path(agent["ref"]).read_text()]
    log.info("running agent: %s %s", agent["kind"], agent["ref"])
    subprocess.run(cmd, check=True)


def _execute_rule(rule: dict) -> None:
    rid = rule.get("id", "?")
    log.info("=== rule %s ===", rid)
    if rule.get("has_deterministic"):
        _run_deterministic(rule.get("deterministic") or [])
    if rule.get("has_agent"):
        outcome = os.environ.get("OUTCOME_YAML")
        if outcome:
            Path(outcome).unlink(missing_ok=True)  # reset per agent
        _run_agent(rule["agent"])
        if rule.get("has_post_deterministic"):
            _run_deterministic(rule.get("post_deterministic") or [])
        if rule.get("has_on_outcome") and rule.get("on_outcome"):
            apply(rule["on_outcome"], rid)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rules = _read_rules()
    if not rules:
        log.info("no matched rules")
        return 0
    for rule in rules:
        _execute_rule(rule)
    return 0


if __name__ == "__main__":
    sys.exit(main())
