"""Unit tests for the run_rule driver (pipeline ordering)."""

from __future__ import annotations

from llm_augmented_workflows import apply_outcome, run_rule, run_steps


def _rule(*, pre=False, post=False, outcome=False, agent=True):
    return {
        "id": "r",
        "has_deterministic": pre,
        "deterministic": [{"labels": {"add": ["pre"]}}] if pre else [],
        "has_agent": agent,
        "agent": {
            "kind": "skill",
            "ref": "x",
            "model": "m",
            "agents_repository": "r",
            "timeout_minutes": None,
        },
        "has_post_deterministic": post,
        "post_deterministic": [{"labels": {"remove": ["post"]}}] if post else [],
        "has_on_outcome": outcome,
        "on_outcome": {"cases": {"approved": {"labels": {"add": ["done"]}}}, "default": None}
        if outcome
        else None,
    }


def test_run_rule_orders_pre_agent_post_outcome(monkeypatch):
    calls = []
    monkeypatch.setattr(run_steps, "apply_labels", lambda step: calls.append(("labels", step)))
    monkeypatch.setattr(run_steps, "run_shell", lambda step: calls.append(("shell", step)))
    monkeypatch.setattr(
        run_rule.subprocess, "run", lambda cmd, **k: calls.append(("agent", cmd)) or None
    )
    monkeypatch.setattr(run_rule, "apply", lambda oc, rid="": calls.append(("outcome", rid)))
    monkeypatch.delenv("OUTCOME_YAML", raising=False)

    run_rule._execute_rule(_rule(pre=True, post=True, outcome=True))

    assert [c[0] for c in calls] == ["labels", "agent", "labels", "outcome"]


def test_run_rule_skips_post_and_outcome_without_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(run_steps, "apply_labels", lambda step: calls.append(("labels", step)))
    monkeypatch.setattr(run_rule.subprocess, "run", lambda cmd, **k: calls.append(("agent", cmd)))
    monkeypatch.setattr(run_rule, "apply", lambda oc, rid="": calls.append(("outcome", rid)))

    # post-deterministic / on_outcome only run after an agent
    run_rule._execute_rule(_rule(pre=True, post=True, outcome=True, agent=False))

    assert [c[0] for c in calls] == ["labels"]


def test_apply_outcome_reused_by_run_rule_is_the_same_function():
    # run_rule imports apply by name; ensure it is apply_outcome.apply
    assert run_rule.apply is apply_outcome.apply
