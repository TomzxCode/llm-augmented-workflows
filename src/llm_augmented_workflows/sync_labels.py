#!/usr/bin/env python3
"""Create or update the labels declared under ``labels:`` in flows.yml."""

from __future__ import annotations

import logging
import os
import sys

from .engine import load_flows
from .trackers import load_tracker

log = logging.getLogger("sync_labels")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    flows = load_flows(os.environ.get("FLOWS_FILE", ".github/llmaw/flows.yml"))
    labels = flows.get("labels") or []
    if not labels:
        log.warning("no labels declared in flows.yml")
        return 0
    try:
        client = load_tracker(flows)
    except ValueError as exc:
        log.error("%s", exc)
        return 1
    client.sync_labels(labels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
