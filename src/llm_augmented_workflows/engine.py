"""Core engine: load flows.yml, match events to rules, resolve steps.

This module is intentionally free of GitHub/HTTP side effects so it can be unit
tested directly. The CLI entrypoints (``route.py``, ``run_steps.py``,
``sync_labels.py``) wrap these pure functions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

DETERMINISTIC_KINDS: tuple[str, ...] = ("labels", "shell")
AGENT_KINDS: tuple[str, ...] = ("skill", "prompt")
ALL_KINDS: tuple[str, ...] = DETERMINISTIC_KINDS + AGENT_KINDS


class ConfigError(Exception):
    """Raised when ``flows.yml`` is structurally invalid."""


@dataclass(frozen=True)
class When:
    event: str | None = None
    action: str | None = None
    label: str | None = None
    merged: bool | None = None
    branch_prefix: str | None = None
    body_contains: str | None = None


@dataclass(frozen=True)
class AgentStep:
    kind: str
    ref: str
    model: str
    agents_repository: str
    timeout_minutes: int | None = None


@dataclass(frozen=True)
class Rule:
    id: str
    flow: str
    when: When
    deterministic: list[dict[str, Any]]
    agent: AgentStep | None


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_flows(path: str | Path) -> dict[str, Any]:
    """Load and return the raw ``flows.yml`` document."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"flows file not found: {p}")
    data = yaml.safe_load(p.read_text()) or {}
    if not isinstance(data, dict):
        raise ConfigError("flows file must contain a mapping at the top level")
    return data


def parse_when(raw: dict[str, Any]) -> When:
    merged = raw.get("merged")
    if merged is not None:
        merged = bool(merged)
    return When(
        event=raw.get("event"),
        action=raw.get("action"),
        label=raw.get("label"),
        merged=merged,
        branch_prefix=raw.get("branch_prefix"),
        body_contains=raw.get("body_contains"),
    )


# --------------------------------------------------------------------------- #
# run: normalization + validation
# --------------------------------------------------------------------------- #
def normalize_run(run: Any) -> list[dict[str, Any]]:
    """Coerce a ``run`` value into an ordered list of single-key step dicts."""
    if isinstance(run, dict):
        run = [run]
    if not isinstance(run, list):
        raise ConfigError("run must be a list or a single step object")
    steps: list[dict[str, Any]] = []
    for i, item in enumerate(run):
        if not isinstance(item, dict) or len(item) != 1:
            raise ConfigError(f"step #{i} must be an object with exactly one key")
        kind = next(iter(item))
        if kind not in ALL_KINDS:
            raise ConfigError(f"step #{i} has unknown kind '{kind}'")
        steps.append(item)
    return steps


def split_steps(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Split steps into deterministic ones and (at most one) agent step.

    Deterministic steps must precede the agent step.
    """
    deterministic: list[dict[str, Any]] = []
    agent: dict[str, Any] | None = None
    for step in steps:
        kind = next(iter(step))
        if kind in DETERMINISTIC_KINDS:
            if agent is not None:
                raise ConfigError("deterministic steps must come before the agent step")
            deterministic.append(step)
        else:
            if agent is not None:
                raise ConfigError("only one agent step per rule is supported in v1")
            agent = step
    return deterministic, agent


def _step_value(agent_step: dict[str, Any]) -> tuple[str, Any]:
    kind = next(iter(agent_step))
    return kind, agent_step[kind]


def build_agent(
    agent_step: dict[str, Any],
    defaults: dict[str, Any],
    base_model: str,
    base_agents_repo: str,
) -> AgentStep:
    kind, value = _step_value(agent_step)
    overrides: dict[str, Any] = {}
    if isinstance(value, dict):
        ref = value.get("name") or value.get("path") or value.get("ref")
        overrides = {k: v for k, v in value.items() if k not in {"name", "path", "ref"}}
    else:
        ref = value
    if not ref or not isinstance(ref, str):
        raise ConfigError(f"{kind} step is missing a name/path")

    model = overrides.get("model") or defaults.get("model") or base_model
    agents_repo = (
        overrides.get("agents_repository") or defaults.get("agents_repository") or base_agents_repo
    )
    timeout = overrides.get("timeout_minutes") or defaults.get("timeout_minutes")

    return AgentStep(
        kind=kind,
        ref=ref,
        model=model,
        agents_repository=agents_repo,
        timeout_minutes=int(timeout) if timeout is not None else None,
    )


def flatten_rules(
    flows_raw: dict[str, Any],
    base_model: str,
    base_agents_repo: str,
) -> list[Rule]:
    """Flatten every rule across every flow into a single ordered list."""
    defaults = flows_raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("defaults must be a mapping")
    flows = flows_raw.get("flows") or {}
    if not isinstance(flows, dict):
        raise ConfigError("flows must be a mapping")

    rules: list[Rule] = []
    for flow_name, flow_body in flows.items():
        flow_rules = (flow_body or {}).get("rules") or []
        for rule_raw in flow_rules:
            if not isinstance(rule_raw, dict):
                raise ConfigError(f"rule in flow '{flow_name}' must be a mapping")
            rid = rule_raw.get("id")
            if not rid:
                raise ConfigError(f"rule in flow '{flow_name}' is missing an id")
            when = parse_when(rule_raw.get("when") or {})
            steps = normalize_run(rule_raw.get("run"))
            if not steps:
                raise ConfigError(f"rule '{rid}' has no steps")
            deterministic, agent_step = split_steps(steps)
            agent = (
                build_agent(agent_step, defaults, base_model, base_agents_repo)
                if agent_step
                else None
            )
            rules.append(
                Rule(
                    id=str(rid),
                    flow=str(flow_name),
                    when=when,
                    deterministic=deterministic,
                    agent=agent,
                )
            )
    return rules


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
def matches(when: When, event_name: str, payload: dict[str, Any]) -> bool:
    """Return True if ``when`` matches the given GitHub event."""
    if when.event and when.event != event_name:
        return False
    if when.action is not None and when.action != payload.get("action"):
        return False
    if when.label is not None:
        label_name = ((payload.get("label") or {}).get("name"))
        if when.label != label_name:
            return False
    if when.merged is not None:
        pr = payload.get("pull_request") or {}
        if bool(pr.get("merged")) != when.merged:
            return False
    if when.branch_prefix:
        pr = payload.get("pull_request") or {}
        ref = (pr.get("head") or {}).get("ref") or ""
        if not str(ref).startswith(when.branch_prefix):
            return False
    if when.body_contains:
        body = (payload.get("issue") or {}).get("body") or (payload.get("pull_request") or {}).get(
            "body"
        )
        if when.body_contains not in (body or ""):
            return False
    return True


# --------------------------------------------------------------------------- #
# Serialization for the Actions matrix
# --------------------------------------------------------------------------- #
def normalize_label_step(step: dict[str, Any]) -> dict[str, Any]:
    body = step.get("labels") or {}
    add = body.get("add", [])
    remove = body.get("remove", [])
    if isinstance(add, str):
        add = [add]
    if isinstance(remove, str):
        remove = [remove]
    target = body.get("target", "subject")
    if target not in {"subject", "linked-issue"}:
        raise ConfigError(f"labels target '{target}' is not supported")
    return {"labels": {"add": list(add), "remove": list(remove), "target": target}}


def agent_to_dict(agent: AgentStep) -> dict[str, Any]:
    return {
        "kind": agent.kind,
        "ref": agent.ref,
        "model": agent.model,
        "agents_repository": agent.agents_repository,
        "timeout_minutes": agent.timeout_minutes,
    }


def rule_to_matrix(rule: Rule) -> dict[str, Any]:
    deterministic = [
        normalize_label_step(s) if "labels" in s else s for s in rule.deterministic
    ]
    return {
        "id": rule.id,
        "flow": rule.flow,
        "has_deterministic": len(deterministic) > 0,
        "has_agent": rule.agent is not None,
        "deterministic": deterministic,
        "agent": agent_to_dict(rule.agent) if rule.agent else None,
    }


# --------------------------------------------------------------------------- #
# Label diff (deterministic, tested)
# --------------------------------------------------------------------------- #
def compute_label_diff(
    current: list[str], add: list[str], remove: list[str]
) -> tuple[list[str], list[str]]:
    """Return (to_add, to_remove) making the operation idempotent."""
    present = set(current)
    to_add = [label for label in add if label not in present]
    to_remove = [label for label in remove if label in present]
    return to_add, to_remove
