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

from . import engine, run_steps
from .apply_outcome import apply
from .engine import NEEDS_HUMAN_LABEL, ConfigError

log = logging.getLogger("run_rule")


def _read_rules() -> list[dict]:
    matched_file = os.environ.get("MATCHED_FILE")
    if matched_file and Path(matched_file).exists():
        return json.loads(Path(matched_file).read_text())
    raw = os.environ.get("MATCHED_RULE")
    return [json.loads(raw)] if raw else []


def _resolve_execution() -> str:
    value = (os.environ.get("EXECUTION") or "").strip().lower()
    return value if value in engine.EXECUTION_MODES else engine.DEFAULT_EXECUTION


def _load_all_rules() -> list[engine.Rule]:
    """Load the flat rule list from ``flows.yml`` for continuous chaining."""
    flows_path = os.environ.get("FLOWS_FILE", ".github/llmaw/flows.yml")
    base_model = os.environ.get("MODEL", "")
    base_agents_repo = os.environ.get("AGENTS_REPOSITORY", "")
    try:
        flows_raw = engine.load_flows(flows_path)
    except ConfigError as exc:
        log.error("cannot load flows for continuous chaining: %s", exc)
        return []
    return engine.flatten_rules(flows_raw, base_model, base_agents_repo)


def _fetch_labels(number: int, kind: str) -> list[str]:
    return run_steps._current_labels(number, kind)


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


def _run_continuous(seed_rules: list[dict]) -> int:
    """Run the seed rules, then keep chaining to the next rule based on the
    labels each rule adds, until a terminal condition is reached.

    Terminals: ``llmaw:needs-human`` appears on the subject, a rule adds no new
    label, no rule matches the newly-added labels, or the iteration cap fires.

    Continuous chaining only applies to issue subjects (the label state-machine
    lives on issues). PR/comment subjects run the seed once without looping;
    any relabel they cause on a linked issue triggers its own dispatch, which
    will itself be continuous.
    """
    number, kind = run_steps._current_subject()
    if kind != "issue" or number is None:
        for rule in seed_rules:
            _execute_rule(rule)
        log.info(
            "continuous: subject is not an issue (%s); ran seed without looping", kind
        )
        return 0

    all_rules = _load_all_rules()
    seen = set(_fetch_labels(number, kind))
    batch = seed_rules
    max_iter = int(os.environ.get("LLMAW_MAX_ITERATIONS", "30"))

    iterations = 0
    while batch:
        iterations += 1
        if iterations > max_iter:
            log.warning("continuous: hit iteration cap (%d); stopping", max_iter)
            break
        for rule in batch:
            _execute_rule(rule)

        current = set(_fetch_labels(number, kind))
        if NEEDS_HUMAN_LABEL in current:
            log.info("continuous: %s present; stopping", NEEDS_HUMAN_LABEL)
            break
        new_labels = current - seen
        if not new_labels:
            log.info("continuous: no new labels after iteration %d; stopping", iterations)
            break
        next_rules = engine.find_next_rules(all_rules, sorted(new_labels))
        if not next_rules:
            log.info(
                "continuous: no next rule matches new labels %s; stopping",
                sorted(new_labels),
            )
            break
        seen = current
        batch = [engine.rule_to_matrix(r) for r in next_rules]
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rules = _read_rules()
    if not rules:
        log.info("no matched rules")
        return 0
    execution = _resolve_execution()
    log.info("execution mode: %s", execution)
    if execution == "continuous":
        return _run_continuous(rules)
    for rule in rules:
        _execute_rule(rule)
    return 0


if __name__ == "__main__":
    sys.exit(main())
