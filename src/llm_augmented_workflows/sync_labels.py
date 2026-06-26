#!/usr/bin/env python3
"""Create or update repository labels declared under ``labels:`` in flows.yml."""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from .engine import load_flows

log = logging.getLogger("sync_labels")


def sync_label(name: str, description: str, color: str) -> None:
    """Create a label, or update it if it already exists."""
    create = subprocess.run(
        ["gh", "label", "create", name, "--description", description, "--color", color],
        capture_output=True,
        text=True,
    )
    if create.returncode == 0:
        log.info("created label %s", name)
        return
    subprocess.run(
        ["gh", "label", "edit", name, "--description", description, "--color", color],
        check=True,
    )
    log.info("updated label %s", name)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    flows = load_flows(os.environ.get("FLOWS_FILE", ".github/llmaw/flows.yml"))
    labels = flows.get("labels") or []
    if not labels:
        log.warning("no labels declared in flows.yml")
        return 0
    for label in labels:
        sync_label(
            name=label["name"],
            description=label.get("description", ""),
            color=label.get("color", ""),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
