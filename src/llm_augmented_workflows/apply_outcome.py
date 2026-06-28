#!/usr/bin/env python3
"""Apply a rule's ``on_outcome`` action from the agent's emitted outcome.

Reads the matched rule from ``MATCHED_RULE`` (the Actions matrix entry JSON) and
the agent's outcome from ``OUTCOME_YAML`` (a YAML file the skill wrote). Selects
the action for ``outcome.verdict`` (falling back to the ``_`` default) and
applies its labels / close / comment to the subject (or linked issue).

GitHub mutations use ``gh`` with ``GH_TOKEN``, the same contract as
``run_steps.py``. Reuses ``run_steps`` helpers so label/close behavior stays
consistent.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import yaml

from . import run_steps

log = logging.getLogger("apply_outcome")


def _read_outcome() -> dict:
    path = os.environ.get("OUTCOME_YAML")
    if not path or not Path(path).exists():
        log.warning("no outcome file at OUTCOME_YAML=%s", path or "(unset)")
        return {}
    try:
        data = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as exc:
        log.warning("invalid outcome yaml at %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        log.warning("outcome yaml is not a mapping: %r", data)
        return {}
    return data


def outcome_present() -> bool:
    """True if ``$OUTCOME_YAML`` exists and declares a ``verdict``."""
    return bool(_read_outcome().get("verdict"))


def _post_comment(number: int, kind: str, body: str) -> None:
    run_steps._gh([kind, "comment", str(number), "--body", body])


def _close(number: int, kind: str, comment: str | None) -> None:
    args = [kind, "close", str(number)]
    if comment:
        args += ["--comment", comment]
    run_steps._gh(args)


def apply(on_outcome: dict, rule_id: str = "") -> int:
    """Read ``$OUTCOME_YAML`` and apply the matched ``on_outcome`` action."""
    outcome = _read_outcome()
    verdict = str(outcome.get("verdict") or "unknown")
    cases = on_outcome.get("cases") or {}
    default = on_outcome.get("default")
    action = cases.get(verdict, default)

    if action is None:
        log.warning("no on_outcome case for verdict '%s' and no default; posting a notice", verdict)
        number, kind = run_steps._current_subject()
        if number is not None:
            _post_comment(
                number,
                kind,
                f"Skill produced no actionable outcome (`verdict: {verdict}`). Needs review.",
            )
        return 0

    log.info("rule %s outcome verdict='%s' -> action=%s", rule_id, verdict, action)

    labels = action.get("labels") or {}
    if labels.get("add") or labels.get("remove"):
        run_steps.apply_labels({"labels": labels})

    number, kind = run_steps._current_subject()
    if number is None:
        log.warning("no subject (ISSUE_NUMBER/PR_NUMBER unset); close/comment skipped")
        return 0
    if action.get("close"):
        _close(number, kind, action.get("comment"))
    elif action.get("comment"):
        _post_comment(number, kind, action["comment"])

    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raw = os.environ.get("MATCHED_RULE")
    if not raw:
        log.error("MATCHED_RULE env var is not set")
        return 1
    rule = json.loads(raw)
    on_outcome = rule.get("on_outcome")
    if not on_outcome:
        log.info("rule %s has no on_outcome; nothing to apply", rule.get("id"))
        return 0
    return apply(on_outcome, rule.get("id", ""))


if __name__ == "__main__":
    sys.exit(main())
