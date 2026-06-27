"""Command-line interface for the LLM-Augmented Workflows engine.

Each subcommand reads its inputs from environment variables (the same contract
the GitHub Actions workflow sets). Installed as the ``llmaw`` console script.
"""

from __future__ import annotations

import argparse
import sys

from . import apply_outcome, route, run_rule, run_steps, sync_labels


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="llmaw",
        description="LLM-Augmented Workflows engine.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("route", help="match a GitHub event to flows.yml rules")
    run_steps_parser = sub.add_parser(
        "run-steps", help="run the deterministic steps of a matched rule"
    )
    run_steps_parser.add_argument("phase", nargs="?", default="pre", choices=["pre", "post"])
    sub.add_parser(
        "run-rule",
        help="execute matched rules end to end (pre -> agent -> post -> on_outcome)",
    )
    sub.add_parser("apply-outcome", help="apply a rule's on_outcome action from $OUTCOME_YAML")
    sub.add_parser("sync-labels", help="create/update labels declared in flows.yml")

    args = parser.parse_args()
    if args.command == "run-steps":
        return run_steps.main(args.phase)
    commands = {
        "route": route.main,
        "run-rule": run_rule.main,
        "apply-outcome": apply_outcome.main,
        "sync-labels": sync_labels.main,
    }
    return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())
