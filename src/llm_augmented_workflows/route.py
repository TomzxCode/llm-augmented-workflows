#!/usr/bin/env python3
"""Route an event to the matching rules in ``flows.yml``.

Reads the event from an :class:`EventSource` (the GitHub Actions runtime by
default, i.e. ``GITHUB_EVENT_NAME`` / ``GITHUB_EVENT_PATH``) and writes two
outputs to ``$GITHUB_OUTPUT``:

* ``matched`` - a JSON array of matched rules (one Actions matrix entry each)
* ``count``   - the number of matched rules
"""

from __future__ import annotations

import json
import logging
import os
import sys

from .engine import (
    ConfigError,
    flatten_rules,
    load_flows,
    matches,
    resolve_dispatch_execution,
    rule_to_matrix,
)
from .trackers.github import GithubActionsEventSource

log = logging.getLogger("route")


def _write_output(name: str, value: str) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as fh:
            fh.write(f"{name}={value}\n")
    print(f"{name}={value}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    flows_path = os.environ.get("FLOWS_FILE", ".github/llmaw/flows.yml")
    base_model = os.environ.get("MODEL", "")
    base_agents_repo = os.environ.get("AGENTS_REPOSITORY", "")

    try:
        flows_raw = load_flows(flows_path)
        all_rules = flatten_rules(flows_raw, base_model, base_agents_repo)
    except ConfigError as exc:
        log.error("invalid flows config: %s", exc)
        return 1

    source = GithubActionsEventSource()
    if source.event_name() == "workflow_dispatch":
        # Manual dry-run: emit a single rule by id, no event matching.
        force_id = os.environ.get("FORCE_RULE_ID", "").strip()
        rules = [r for r in all_rules if r.id == force_id] if force_id else []
    else:
        event = source.event()
        if event is None:
            log.warning("no event available (GITHUB_EVENT_NAME/GITHUB_EVENT_PATH unset)")
            rules = []
        else:
            rules = [r for r in all_rules if matches(r.when, event)]

    matrix = [rule_to_matrix(r) for r in rules]

    override = (os.environ.get("EXECUTION") or "").strip().lower()
    if override not in ("continuous", "event-driven"):
        override = ""
    execution = resolve_dispatch_execution(flows_raw, rules, override)

    _write_output("matched", json.dumps(matrix))
    _write_output("count", str(len(matrix)))
    _write_output("has_agent", str(any(m.get("has_agent") for m in matrix)))
    _write_output("execution", execution)
    matched_file = os.environ.get("MATCHED_FILE")
    if matched_file:
        with open(matched_file, "w") as fh:
            fh.write(json.dumps(matrix))

    log.info(
        "event=%s execution=%s matched=%s",
        event_name or "(none)",
        execution,
        [m["id"] for m in matrix] or "none",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
