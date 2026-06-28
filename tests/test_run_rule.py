"""Unit tests for the run_rule driver (pipeline ordering)."""

from __future__ import annotations

import textwrap

from llm_augmented_workflows import apply_outcome, engine, run_rule, run_steps


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


class _Proc:
    def __init__(self, rc):
        self.returncode = rc


def test_execute_rule_continues_session_when_outcome_missing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        run_rule.subprocess, "run", lambda cmd, **k: calls.append(("opencode", cmd)) or _Proc(0)
    )
    monkeypatch.setattr(run_rule, "apply", lambda oc, rid="": calls.append(("outcome", rid)))
    monkeypatch.setattr(apply_outcome, "outcome_present", lambda: False)
    monkeypatch.setenv("OUTCOME_YAML", str(tmp_path / "outcome.yaml"))

    run_rule._execute_rule(_rule(outcome=True))

    agent_calls = [c for c in calls if c[0] == "opencode"]
    assert len(agent_calls) == 2  # initial skill run + continuation
    assert "--continue" in agent_calls[1][1]
    assert str(tmp_path / "outcome.yaml") in " ".join(agent_calls[1][1])
    # apply still runs last, after the continuation
    assert calls[-1] == ("outcome", "r")


def test_execute_rule_skips_continuation_when_outcome_present(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        run_rule.subprocess, "run", lambda cmd, **k: calls.append(("opencode", cmd)) or _Proc(0)
    )
    monkeypatch.setattr(run_rule, "apply", lambda oc, rid="": calls.append(("outcome", rid)))
    monkeypatch.setattr(apply_outcome, "outcome_present", lambda: True)
    monkeypatch.setenv("OUTCOME_YAML", str(tmp_path / "outcome.yaml"))

    run_rule._execute_rule(_rule(outcome=True))

    agent_calls = [c for c in calls if c[0] == "opencode"]
    assert len(agent_calls) == 1  # only the initial skill run, no continuation


def test_execute_rule_skips_continuation_without_on_outcome(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        run_rule.subprocess, "run", lambda cmd, **k: calls.append(("opencode", cmd)) or _Proc(0)
    )
    monkeypatch.setattr(apply_outcome, "outcome_present", lambda: False)
    monkeypatch.setenv("OUTCOME_YAML", str(tmp_path / "outcome.yaml"))

    run_rule._execute_rule(_rule(outcome=False))

    agent_calls = [c for c in calls if c[0] == "opencode"]
    assert len(agent_calls) == 1  # no on_outcome -> nothing to continue for


def test_execute_rule_skips_continuation_when_outcome_yaml_unset(monkeypatch):
    calls = []
    monkeypatch.setattr(
        run_rule.subprocess, "run", lambda cmd, **k: calls.append(("opencode", cmd)) or _Proc(0)
    )
    monkeypatch.setattr(run_rule, "apply", lambda oc, rid="": calls.append(("outcome", rid)))
    monkeypatch.delenv("OUTCOME_YAML", raising=False)

    run_rule._execute_rule(_rule(outcome=True))

    agent_calls = [c for c in calls if c[0] == "opencode"]
    assert len(agent_calls) == 1  # no outcome contract -> no continuation


# --------------------------------------------------------------------------- #
# continuous execution loop
# --------------------------------------------------------------------------- #
_CHAIN_FLOWS = """
flows:
  f:
    rules:
      - id: a
        when: {event: issues, action: labeled, label: llmaw:start}
        run: [{skill: x}]
      - id: b
        when: {event: issues, action: labeled, label: llmaw:mid}
        run: [{skill: y}]
"""


def _write_flows(tmp_path, text):
    p = tmp_path / "flows.yml"
    p.write_text(textwrap.dedent(text))
    return p


def _matrix_for(p, rule_id):
    rules = engine.flatten_rules(engine.load_flows(str(p)), "m", "r")
    return engine.rule_to_matrix(next(r for r in rules if r.id == rule_id))


def test_run_continuous_chains_through_new_labels(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    all_rules = engine.flatten_rules(engine.load_flows(str(p)), "m", "r")
    monkeypatch.setattr(run_rule, "_load_all_rules", lambda: all_rules)
    monkeypatch.setattr(run_steps, "_current_subject", lambda: (42, "issue"))

    labels = {"llmaw:start"}
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda n, k: sorted(labels))

    executed = []

    def fake_execute(rule):
        executed.append(rule["id"])
        if rule["id"] == "a":
            labels.add("llmaw:mid")
        elif rule["id"] == "b":
            labels.add("llmaw:end")  # no rule matches -> loop stops here

    monkeypatch.setattr(run_rule, "_execute_rule", fake_execute)

    run_rule._run_continuous([_matrix_for(p, "a")])
    assert executed == ["a", "b"]


def test_run_continuous_stops_on_needs_human(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("ISSUE_NUMBER", "7")
    all_rules = engine.flatten_rules(engine.load_flows(str(p)), "m", "r")
    monkeypatch.setattr(run_rule, "_load_all_rules", lambda: all_rules)
    monkeypatch.setattr(run_steps, "_current_subject", lambda: (7, "issue"))

    labels = {"llmaw:start"}
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda n, k: sorted(labels))

    executed = []

    def fake_execute(rule):
        executed.append(rule["id"])
        labels.add("llmaw:needs-human")
        labels.add("llmaw:mid")  # would normally chain, but needs-human stops it

    monkeypatch.setattr(run_rule, "_execute_rule", fake_execute)

    run_rule._run_continuous([_matrix_for(p, "a")])
    assert executed == ["a"]


def test_run_continuous_stops_when_rule_adds_no_new_label(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("ISSUE_NUMBER", "9")
    all_rules = engine.flatten_rules(engine.load_flows(str(p)), "m", "r")
    monkeypatch.setattr(run_rule, "_load_all_rules", lambda: all_rules)
    monkeypatch.setattr(run_steps, "_current_subject", lambda: (9, "issue"))

    labels = {"llmaw:start"}
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda n, k: sorted(labels))

    executed = []
    # rule a adds nothing (e.g. a plan PR opener with approved: {}) -> no new label
    monkeypatch.setattr(run_rule, "_execute_rule", lambda rule: executed.append(rule["id"]))

    run_rule._run_continuous([_matrix_for(p, "a")])
    assert executed == ["a"]


def test_run_continuous_pr_subject_runs_seed_without_looping(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("PR_NUMBER", "3")
    monkeypatch.setattr(run_steps, "_current_subject", lambda: (3, "pr"))
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda n, k: ["llmaw:mid"])

    executed = []
    monkeypatch.setattr(run_rule, "_execute_rule", lambda rule: executed.append(rule["id"]))
    # even though _load_all_rules would find a chain, PR subjects never loop
    monkeypatch.setattr(
        run_rule,
        "_load_all_rules",
        lambda: engine.flatten_rules(engine.load_flows(str(p)), "m", "r"),
    )

    run_rule._run_continuous([_matrix_for(p, "a")])
    assert executed == ["a"]


def test_run_continuous_respects_iteration_cap(monkeypatch, tmp_path):
    # a self-referencing rule: matches llmaw:loop and keeps re-adding it.
    p = _write_flows(
        tmp_path,
        """
        flows:
          f:
            rules:
              - id: loop
                when: {event: issues, action: labeled, label: llmaw:loop}
                run: [{skill: x}]
        """,
    )
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("LLMAW_MAX_ITERATIONS", "2")
    all_rules = engine.flatten_rules(engine.load_flows(str(p)), "m", "r")
    monkeypatch.setattr(run_rule, "_load_all_rules", lambda: all_rules)
    monkeypatch.setattr(run_steps, "_current_subject", lambda: (1, "issue"))

    labels = {"llmaw:loop"}  # already seen, so re-adding won't look "new"
    # But we want a runaway: make each run add a fresh label that matches itself.
    # Use a counter so each iteration adds a distinct label matched by a rule
    # we inject via find_next. Easiest: monkeypatch find_next to always re-run.
    monkeypatch.setattr(engine, "find_next_rules", lambda rules, new: all_rules if new else [])
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda n, k: sorted(labels))

    executed = []
    counter = {"i": 0}

    def fake_execute(rule):
        executed.append(rule["id"])
        counter["i"] += 1
        labels.add(f"llmaw:tick-{counter['i']}")  # always something new

    monkeypatch.setattr(run_rule, "_execute_rule", fake_execute)

    run_rule._run_continuous([_matrix_for(p, "loop")])
    # cap is 2 iterations
    assert len(executed) == 2


def test_main_event_driven_runs_seed_once_even_if_labels_would_chain(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("MATCHED_RULE", "[]")  # will be overridden below via MATCHED_FILE
    monkeypatch.setenv("EXECUTION", "event-driven")
    monkeypatch.setenv("ISSUE_NUMBER", "5")
    monkeypatch.setattr(run_steps, "_current_subject", lambda: (5, "issue"))

    import json

    monkeypatch.setenv("MATCHED_FILE", str(tmp_path / "matched.json"))
    (tmp_path / "matched.json").write_text(json.dumps([_matrix_for(p, "a")]))

    executed = []

    def fake_execute(rule):
        executed.append(rule["id"])
        # pretend the agent advanced the state machine heavily
        labels = {"llmaw:mid", "llmaw:end"}
        monkeypatch.setattr(run_rule, "_fetch_labels", lambda n, k: sorted(labels))

    monkeypatch.setattr(run_rule, "_execute_rule", fake_execute)
    # ensure continuous path is not taken even though labels would chain
    monkeypatch.setattr(
        run_rule,
        "_load_all_rules",
        lambda: engine.flatten_rules(engine.load_flows(str(p)), "m", "r"),
    )

    assert run_rule.main() == 0
    assert executed == ["a"]


def test_main_continuous_invokes_loop(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    import json

    monkeypatch.setenv("EXECUTION", "continuous")
    monkeypatch.setenv("ISSUE_NUMBER", "8")
    monkeypatch.setenv("MATCHED_FILE", str(tmp_path / "matched.json"))
    (tmp_path / "matched.json").write_text(json.dumps([_matrix_for(p, "a")]))

    called = {"continuous": False}
    monkeypatch.setattr(
        run_rule, "_run_continuous", lambda seed: called.__setitem__("continuous", True) or 0
    )
    assert run_rule.main() == 0
    assert called["continuous"] is True
