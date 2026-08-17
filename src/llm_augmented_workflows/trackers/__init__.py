"""Tracker adapters and the ``load_tracker`` factory.

The tracker is selected per invocation: ``flows.yml`` ``tracker.kind`` wins,
then the ``LLMAW_TRACKER`` environment variable, then the default ``github``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .base import TrackerClient
from .github import GithubCliClient
from .local import LocalYamlClient

DEFAULT_STATE_DIR = ".llmaw/state"


def load_tracker(
    flows_raw: Mapping[str, Any], env: Mapping[str, str] | None = None
) -> TrackerClient:
    """Construct the tracker client for this invocation."""
    env = os.environ if env is None else env
    cfg = flows_raw.get("tracker") or {}
    if not isinstance(cfg, dict):
        raise ValueError("tracker config must be a mapping")
    kind = cfg.get("kind") or env.get("LLMAW_TRACKER") or "github"
    if kind == "github":
        return GithubCliClient()
    if kind == "local":
        return LocalYamlClient(cfg.get("state_dir") or DEFAULT_STATE_DIR)
    raise ValueError(f"unknown tracker kind '{kind}' (expected 'github' or 'local')")
