"""Command-line interface for the LLM-Augmented Workflows engine.

Each subcommand reads its inputs from environment variables (the same contract
the GitHub Actions workflow sets). Installed as the ``llmaw`` console script.
"""

from __future__ import annotations

import argparse
import sys

from . import route, run_steps, sync_labels


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="llmaw",
        description="LLM-Augmented Workflows engine.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("route", help="match a GitHub event to flows.yml rules")
    sub.add_parser("run-steps", help="run the deterministic steps of a matched rule")
    sub.add_parser("sync-labels", help="create/update labels declared in flows.yml")

    args = parser.parse_args()
    commands = {
        "route": route.main,
        "run-steps": run_steps.main,
        "sync-labels": sync_labels.main,
    }
    return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())
