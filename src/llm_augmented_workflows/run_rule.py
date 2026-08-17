#!/usr/bin/env python3
"""Execute matched rules end to end as a single pipeline.

For each matched rule, runs its whole ``run`` in this one process:
pre deterministic (``labels``/``shell``) -> agent (``opencode``) -> post
deterministic -> ``on_outcome``. This driver is the local runner: on GitHub
Actions the dispatcher workflow invokes it per matrix entry, and locally
``llmaw trigger`` / ``llmaw run-rule`` invoke it directly.

Reads the matched rules from ``MATCHED_FILE`` (a JSON list) or a single rule
from ``MATCHED_RULE``. Tracker mutations go through the client constructed
from the ``tracker:`` block in ``flows.yml``. ``opencode`` inherits this
process's environment, so the dispatcher/trigger sets ``GH_TOKEN`` /
``ISSUE_NUMBER`` / ``PR_NUMBER`` / etc. before running this command.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from . import apply_outcome, engine, run_steps
from .apply_outcome import apply
from .engine import NEEDS_HUMAN_LABEL, ConfigError
from .trackers.base import SubjectRef, TrackerClient

log = logging.getLogger("run_rule")


@contextlib.contextmanager
def _log_group(title: str):
    """Fold stdout under a collapsible group in GitHub Actions logs.

    Emits the ``::group::``/``::endgroup::`` workflow commands only inside a
    GitHub Actions runner (detected via ``GITHUB_ACTIONS``); a no-op elsewhere
    so local runs and unit tests stay quiet.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::group::{title}")
    try:
        yield
    finally:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::endgroup::")


def _read_rules() -> list[dict]:
    matched_file = os.environ.get("MATCHED_FILE")
    if matched_file and Path(matched_file).exists():
        return json.loads(Path(matched_file).read_text())
    raw = os.environ.get("MATCHED_RULE")
    return [json.loads(raw)] if raw else []


def _resolve_execution() -> str:
    value = (os.environ.get("EXECUTION") or "").strip().lower()
    return value if value in engine.EXECUTION_MODES else engine.DEFAULT_EXECUTION


def _load_client() -> TrackerClient:
    return run_steps.build_client()


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


def _fetch_labels(ref: SubjectRef, client: TrackerClient) -> list[str]:
    return client.get_labels(ref)


def _run_deterministic(steps: list[dict], client: TrackerClient) -> None:
    for step in steps:
        if "labels" in step:
            run_steps.apply_labels(step, client)
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


def _continue_for_outcome(agent: dict, on_outcome: dict) -> None:
    """Resume the agent's opencode session and ask it to emit an outcome.

    Runs when a rule expects an outcome but the skill wrote none or omitted the
    required ``reason``, giving the model one chance to produce a complete
    ``$OUTCOME_YAML`` before apply_outcome falls back to the default/notice
    path. ``--continue`` resumes the last session in this working directory
    (the skill's own session).
    """
    path = os.environ["OUTCOME_YAML"]
    verdicts = sorted((on_outcome.get("cases") or {}).keys())
    hint = f" (one of: {', '.join(verdicts)})" if verdicts else ""
    prompt = (
        f"Your outcome file at {path} is missing or incomplete. Write YAML to "
        f"{path} now using EXACTLY this format, nothing else:\n"
        f"\n"
        f"```\n"
        f'verdict: "value-here"\n'
        f"reason: |\n"
        f"  reason-here\n"
        f"```\n"
        f"\n"
        f"Rules:\n"
        f"- `verdict` must be a single unindented line holding a quoted string"
        f"{hint}.\n"
        f"- `reason` must use the literal block scalar `|` marker, followed by "
        f"one or more indented lines of context-specific feedback to post on "
        f"the issue.\n"
        f"- Both keys are required. Do not add any other keys, comments, or text."
    )
    cmd = [
        "opencode",
        "run",
        "--continue",
        "--model",
        agent["model"],
        "--dangerously-skip-permissions",
        prompt,
    ]
    log.info("no outcome produced; continuing previous session to request one")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        log.warning("outcome continuation exited %s; falling back", result.returncode)


def _execute_rule(rule: dict, client: TrackerClient) -> None:
    rid = rule.get("id", "?")
    flow = rule.get("flow") or "?"
    with _log_group(f"Rule {rid} ({flow})"):
        log.info("=== rule %s ===", rid)
        if rule.get("has_deterministic"):
            _run_deterministic(rule.get("deterministic") or [], client)
        if rule.get("has_agent"):
            outcome = os.environ.get("OUTCOME_YAML")
            if outcome:
                Path(outcome).unlink(missing_ok=True)  # reset per agent
            _run_agent(rule["agent"])
            if rule.get("has_post_deterministic"):
                _run_deterministic(rule.get("post_deterministic") or [], client)
            if rule.get("has_on_outcome") and rule.get("on_outcome"):
                if os.environ.get("OUTCOME_YAML") and not apply_outcome.outcome_present():
                    _continue_for_outcome(rule["agent"], rule["on_outcome"])
                apply(rule["on_outcome"], rid, client)


def _run_continuous(seed_rules: list[dict], client: TrackerClient) -> int:
    """Run the seed rules, then keep chaining to the next rule based on the
    labels each rule adds, until a terminal condition is reached.

    Terminals: ``llmaw:needs-human`` appears on the subject, a rule adds no new
    label, no rule matches the newly-added labels, or the iteration cap fires.

    Continuous chaining only applies to issue subjects (the label state-machine
    lives on issues). PR/comment subjects run the seed once without looping;
    any relabel they cause on a linked issue triggers its own dispatch, which
    will itself be continuous.
    """
    ref = run_steps.current_subject_ref()
    if ref is None or ref.kind != "issue":
        for rule in seed_rules:
            _execute_rule(rule, client)
        log.info(
            "continuous: subject is not an issue (%s); ran seed without looping",
            ref.kind if ref else "none",
        )
        return 0

    all_rules = _load_all_rules()
    seen = set(_fetch_labels(ref, client))
    batch = seed_rules
    max_iter = int(os.environ.get("LLMAW_MAX_ITERATIONS", "30"))

    iterations = 0
    while batch:
        iterations += 1
        if iterations > max_iter:
            log.warning("continuous: hit iteration cap (%d); stopping", max_iter)
            break
        for rule in batch:
            _execute_rule(rule, client)

        current = set(_fetch_labels(ref, client))
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
    try:
        client = _load_client()
    except (ConfigError, ValueError) as exc:
        log.error("cannot construct tracker client: %s", exc)
        return 1
    execution = _resolve_execution()
    log.info("execution mode: %s", execution)
    if execution == "continuous":
        return _run_continuous(rules, client)
    for rule in rules:
        _execute_rule(rule, client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
