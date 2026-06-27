"""Core engine: load flows.yml, match events to rules, resolve steps.

This module is intentionally free of GitHub/HTTP side effects so it can be unit
tested directly. The CLI entrypoints (``route.py``, ``run_steps.py``,
``sync_labels.py``) wrap these pure functions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

DETERMINISTIC_KINDS: tuple[str, ...] = ("labels", "shell")
AGENT_KINDS: tuple[str, ...] = ("skill", "prompt")
POST_KINDS: tuple[str, ...] = ("on_outcome",)
ALL_KINDS: tuple[str, ...] = DETERMINISTIC_KINDS + AGENT_KINDS + POST_KINDS

EXECUTION_MODES: tuple[str, ...] = ("event-driven", "continuous")
DEFAULT_EXECUTION = "event-driven"
NEEDS_HUMAN_LABEL = "llmaw:needs-human"


class ConfigError(Exception):
    """Raised when ``flows.yml`` is structurally invalid."""


def parse_execution(raw: Any) -> str:
    """Normalize an execution mode value.

    Returns one of :data:`EXECUTION_MODES`. ``None`` resolves to the default.
    """
    if raw is None:
        return DEFAULT_EXECUTION
    if not isinstance(raw, str):
        raise ConfigError(
            f"execution must be a string in {EXECUTION_MODES}, got {raw!r}"
        )
    value = raw.strip().lower()
    if value not in EXECUTION_MODES:
        raise ConfigError(f"execution must be one of {EXECUTION_MODES}, got {raw!r}")
    return value


def resolve_execution_for_flow(
    flows_raw: dict[str, Any], flow_name: str, override: str | None
) -> str:
    """Resolve the execution mode for a single flow.

    ``override`` (from a workflow input / repo variable) wins when it is a valid
    mode. Otherwise the flow's own ``execution`` is consulted, then
    ``defaults.execution``, then the hardcoded default.
    """
    if override in EXECUTION_MODES:
        return override
    flows = flows_raw.get("flows") or {}
    flow_body = flows.get(flow_name)
    if isinstance(flow_body, dict) and flow_body.get("execution") is not None:
        return parse_execution(flow_body.get("execution"))
    defaults = flows_raw.get("defaults") or {}
    if isinstance(defaults, dict) and defaults.get("execution") is not None:
        return parse_execution(defaults.get("execution"))
    return DEFAULT_EXECUTION


def resolve_dispatch_execution(
    flows_raw: dict[str, Any], rules: list[Rule], override: str | None
) -> str:
    """Pick a single execution mode for a dispatch run.

    A forced ``override`` applies to the whole run. Otherwise each matched
    rule's flow is resolved independently; if any flow is continuous the run is
    continuous (the richer behavior), else it is event-driven. A run with no
    matched rules is event-driven.
    """
    if override in EXECUTION_MODES:
        return override
    if not rules:
        return DEFAULT_EXECUTION
    modes = {resolve_execution_for_flow(flows_raw, r.flow, None) for r in rules}
    return "continuous" if "continuous" in modes else DEFAULT_EXECUTION


def find_next_rules(rules: list[Rule], new_labels: list[str]) -> list[Rule]:
    """Return issue-labeled rules whose trigger label is in ``new_labels``.

    Continuous mode uses this to decide what to run next based on the labels a
    previous rule just added. Only rules gated on an ``issues`` ``labeled``
    event with an explicit ``label`` are considered, so event-agnostic rules and
    PR/comment rules are never auto-chained. Other ``when`` fields
    (``body_contains`` etc.) are ignored: continuous chaining keys on the label
    alone.
    """
    if not new_labels:
        return []
    wanted = set(new_labels)
    found: list[Rule] = []
    for rule in rules:
        w = rule.when
        if w.event not in (None, "issues"):
            continue
        if w.action not in (None, "labeled"):
            continue
        if w.label is None:
            continue
        if w.label in wanted:
            found.append(rule)
    return found


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
    post_deterministic: list[dict[str, Any]] = field(default_factory=list)
    on_outcome: dict[str, Any] | None = None


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


def split_steps(
    steps: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
    list[dict[str, Any]],
    dict[str, Any] | None,
]:
    """Split steps into pre-agent, the agent, post-agent, and on_outcome.

    ``labels``/``shell`` steps may appear on either side of the agent (pre or
    post) in any order. ``on_outcome`` must follow the agent (it reads the
    outcome file the agent writes) and must be last. At most one agent step and
    one ``on_outcome`` step are supported.
    """
    pre: list[dict[str, Any]] = []
    agent: dict[str, Any] | None = None
    post: list[dict[str, Any]] = []
    on_outcome: dict[str, Any] | None = None
    for step in steps:
        kind = next(iter(step))
        if kind in DETERMINISTIC_KINDS:
            if on_outcome is not None:
                raise ConfigError("labels/shell steps must come before on_outcome")
            (post if agent is not None else pre).append(step)
        elif kind in AGENT_KINDS:
            if agent is not None:
                raise ConfigError("only one agent step per rule is supported")
            agent = step
        elif kind in POST_KINDS:
            if agent is None:
                raise ConfigError("on_outcome step must come after the agent step")
            if on_outcome is not None:
                raise ConfigError("only one on_outcome step per rule is supported")
            on_outcome = step
        else:  # pragma: no cover - normalize_run rejects unknown kinds first
            raise ConfigError(f"unknown step kind '{kind}'")
    return pre, agent, post, on_outcome


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
            deterministic, agent_step, post_steps, outcome_step = split_steps(steps)
            agent = (
                build_agent(agent_step, defaults, base_model, base_agents_repo)
                if agent_step
                else None
            )
            on_outcome = normalize_on_outcome(outcome_step) if outcome_step else None
            rules.append(
                Rule(
                    id=str(rid),
                    flow=str(flow_name),
                    when=when,
                    deterministic=deterministic,
                    agent=agent,
                    post_deterministic=post_steps,
                    on_outcome=on_outcome,
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
        label_name = (payload.get("label") or {}).get("name")
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


def normalize_action(action: Any, case_key: str) -> dict[str, Any]:
    """Normalize one verdict action inside an ``on_outcome`` mapping.

    The label operation uses the same shape as a ``labels`` step:
    ``{labels: {add: [...], remove: [...], target: subject | linked-issue}}``.
    """
    if action is None:
        action = {}
    if not isinstance(action, dict):
        raise ConfigError(f"on_outcome case '{case_key}' must be a mapping")
    labels_body = action.get("labels")
    if labels_body is None:
        labels = {"add": [], "remove": [], "target": "subject"}
    elif isinstance(labels_body, dict):
        labels = normalize_label_step({"labels": labels_body})["labels"]
    else:
        raise ConfigError(f"on_outcome case '{case_key}' labels must be a mapping")
    close = action.get("close", False)
    if not isinstance(close, bool):
        raise ConfigError(f"on_outcome case '{case_key}' close must be a boolean")
    comment = action.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise ConfigError(f"on_outcome case '{case_key}' comment must be a string")
    return {"labels": labels, "close": close, "comment": comment}


def normalize_on_outcome(step: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize an ``on_outcome`` step into {cases, default}.

    Each key (besides the optional ``_`` default) is a verdict string mapped to
    an action. The ``_`` key is the fallback used when no case matches.
    """
    body = step.get("on_outcome")
    if not isinstance(body, dict) or not body:
        raise ConfigError("on_outcome must be a non-empty mapping of verdict -> action")
    cases: dict[str, dict[str, Any]] = {}
    default: dict[str, Any] | None = None
    for key, action in body.items():
        if key == "_":
            default = normalize_action(action, "_")
        else:
            cases[str(key)] = normalize_action(action, str(key))
    if not cases:
        raise ConfigError("on_outcome needs at least one verdict case besides '_'")
    return {"cases": cases, "default": default}


def agent_to_dict(agent: AgentStep) -> dict[str, Any]:
    return {
        "kind": agent.kind,
        "ref": agent.ref,
        "model": agent.model,
        "agents_repository": agent.agents_repository,
        "timeout_minutes": agent.timeout_minutes,
    }


def rule_to_matrix(rule: Rule) -> dict[str, Any]:
    deterministic = [normalize_label_step(s) if "labels" in s else s for s in rule.deterministic]
    post = [normalize_label_step(s) if "labels" in s else s for s in rule.post_deterministic]
    return {
        "id": rule.id,
        "flow": rule.flow,
        "has_deterministic": len(deterministic) > 0,
        "has_agent": rule.agent is not None,
        "has_post_deterministic": len(post) > 0,
        "has_on_outcome": rule.on_outcome is not None,
        "deterministic": deterministic,
        "post_deterministic": post,
        "agent": agent_to_dict(rule.agent) if rule.agent else None,
        "on_outcome": rule.on_outcome,
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
