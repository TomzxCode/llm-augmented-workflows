"""Unit tests for the run_rule driver (pipeline ordering)."""

from __future__ import annotations

import json
import textwrap

from llm_augmented_workflows import apply_outcome, engine, run_rule, run_steps
from llm_augmented_workflows.trackers.base import SubjectRef


class FakeClient:
    name = "fake"

    def __init__(self):
        self.labels: list[str] = []
        self.calls: list[tuple] = []

    def get_labels(self, ref):
        return list(self.labels)

    def add_labels(self, ref, labels):
        self.calls.append(("add_labels", ref, labels))
        for label in labels:
            if label not in self.labels:
                self.labels.append(label)

    def remove_labels(self, ref, labels):
        self.calls.append(("remove_labels", ref, labels))
        self.labels = [item for item in self.labels if item not in set(labels)]

    def comment(self, ref, body):
        self.calls.append(("comment", ref, body))

    def close(self, ref, comment):
        self.calls.append(("close", ref, comment))

    def find_linked_subject(self, ref):
        return None

    def sync_labels(self, defs):
        self.calls.append(("sync_labels", defs))


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
    monkeypatch.setattr(
        run_steps, "apply_labels", lambda step, client=None: calls.append(("labels", step))
    )
    monkeypatch.setattr(run_steps, "run_shell", lambda step: calls.append(("shell", step)))
    monkeypatch.setattr(
        run_rule.subprocess, "run", lambda cmd, **k: calls.append(("agent", cmd)) or None
    )
    monkeypatch.setattr(
        run_rule, "apply", lambda oc, rid="", client=None: calls.append(("outcome", rid))
    )
    monkeypatch.delenv("OUTCOME_YAML", raising=False)

    run_rule._execute_rule(_rule(pre=True, post=True, outcome=True), FakeClient())

    assert [c[0] for c in calls] == ["labels", "agent", "labels", "outcome"]


def test_run_rule_skips_post_and_outcome_without_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        run_steps, "apply_labels", lambda step, client=None: calls.append(("labels", step))
    )
    monkeypatch.setattr(run_rule.subprocess, "run", lambda cmd, **k: calls.append(("agent", cmd)))
    monkeypatch.setattr(
        run_rule, "apply", lambda oc, rid="", client=None: calls.append(("outcome", rid))
    )

    # post-deterministic / on_outcome only run after an agent
    run_rule._execute_rule(_rule(pre=True, post=True, outcome=True, agent=False), FakeClient())

    assert [c[0] for c in calls] == ["labels"]


def test_apply_outcome_reused_by_run_rule_is_the_same_function():
    # run_rule imports apply by name; ensure it is apply_outcome.apply
    assert run_rule.apply is apply_outcome.apply


# --------------------------------------------------------------------------- #
# GitHub Actions log grouping
# --------------------------------------------------------------------------- #
def test_log_group_emits_workflow_commands_in_ci(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with run_rule._log_group("Rule r (f)"):
        print("body")
    out = capsys.readouterr().out
    assert out.startswith("::group::Rule r (f)\n")
    assert out.endswith("::endgroup::\n")
    assert "body\n" in out


def test_log_group_is_silent_outside_ci(capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with run_rule._log_group("Rule r (f)"):
        print("body")
    out = capsys.readouterr().out
    assert out == "body\n"


def test_log_group_closes_even_on_exception(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    try:
        with run_rule._log_group("Rule r (f)"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert capsys.readouterr().out.endswith("::endgroup::\n")


def test_execute_rule_wraps_invocation_in_group(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    calls = []
    monkeypatch.setattr(
        run_steps, "apply_labels", lambda step, client=None: calls.append(("labels", step))
    )
    monkeypatch.setattr(run_rule.subprocess, "run", lambda cmd, **k: calls.append(("agent", cmd)))

    run_rule._execute_rule(_rule(pre=True), FakeClient())

    out = capsys.readouterr().out
    assert out.startswith("::group::Rule r (?)\n")
    assert out.rstrip().endswith("::endgroup::")
    # body still runs (pre labels then agent, since _rule defaults agent=True)
    assert [c[0] for c in calls] == ["labels", "agent"]


class _Proc:
    def __init__(self, rc):
        self.returncode = rc


def test_execute_rule_continues_session_when_outcome_missing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        run_rule.subprocess, "run", lambda cmd, **k: calls.append(("opencode", cmd)) or _Proc(0)
    )
    monkeypatch.setattr(
        run_rule, "apply", lambda oc, rid="", client=None: calls.append(("outcome", rid))
    )
    monkeypatch.setattr(apply_outcome, "outcome_present", lambda: False)
    monkeypatch.setenv("OUTCOME_YAML", str(tmp_path / "outcome.yaml"))

    run_rule._execute_rule(_rule(outcome=True), FakeClient())

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
    monkeypatch.setattr(
        run_rule, "apply", lambda oc, rid="", client=None: calls.append(("outcome", rid))
    )
    monkeypatch.setattr(apply_outcome, "outcome_present", lambda: True)
    monkeypatch.setenv("OUTCOME_YAML", str(tmp_path / "outcome.yaml"))

    run_rule._execute_rule(_rule(outcome=True), FakeClient())

    agent_calls = [c for c in calls if c[0] == "opencode"]
    assert len(agent_calls) == 1  # only the initial skill run, no continuation


def test_execute_rule_skips_continuation_without_on_outcome(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        run_rule.subprocess, "run", lambda cmd, **k: calls.append(("opencode", cmd)) or _Proc(0)
    )
    monkeypatch.setattr(apply_outcome, "outcome_present", lambda: False)
    monkeypatch.setenv("OUTCOME_YAML", str(tmp_path / "outcome.yaml"))

    run_rule._execute_rule(_rule(outcome=False), FakeClient())

    agent_calls = [c for c in calls if c[0] == "opencode"]
    assert len(agent_calls) == 1  # no on_outcome -> nothing to continue for


def test_execute_rule_skips_continuation_when_outcome_yaml_unset(monkeypatch):
    calls = []
    monkeypatch.setattr(
        run_rule.subprocess, "run", lambda cmd, **k: calls.append(("opencode", cmd)) or _Proc(0)
    )
    monkeypatch.setattr(
        run_rule, "apply", lambda oc, rid="", client=None: calls.append(("outcome", rid))
    )
    monkeypatch.delenv("OUTCOME_YAML", raising=False)

    run_rule._execute_rule(_rule(outcome=True), FakeClient())

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
    monkeypatch.setattr(
        run_steps, "current_subject_ref", lambda: SubjectRef("issue", "42")
    )

    labels = {"llmaw:start"}
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda ref, client: sorted(labels))

    executed = []

    def fake_execute(rule, client):
        executed.append(rule["id"])
        if rule["id"] == "a":
            labels.add("llmaw:mid")
        elif rule["id"] == "b":
            labels.add("llmaw:end")  # no rule matches -> loop stops here

    monkeypatch.setattr(run_rule, "_execute_rule", fake_execute)

    run_rule._run_continuous([_matrix_for(p, "a")], FakeClient())
    assert executed == ["a", "b"]


def test_run_continuous_stops_on_needs_human(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("ISSUE_NUMBER", "7")
    all_rules = engine.flatten_rules(engine.load_flows(str(p)), "m", "r")
    monkeypatch.setattr(run_rule, "_load_all_rules", lambda: all_rules)
    monkeypatch.setattr(run_steps, "current_subject_ref", lambda: SubjectRef("issue", "7"))

    labels = {"llmaw:start"}
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda ref, client: sorted(labels))

    executed = []

    def fake_execute(rule, client):
        executed.append(rule["id"])
        labels.add("llmaw:needs-human")
        labels.add("llmaw:mid")  # would normally chain, but needs-human stops it

    monkeypatch.setattr(run_rule, "_execute_rule", fake_execute)

    run_rule._run_continuous([_matrix_for(p, "a")], FakeClient())
    assert executed == ["a"]


def test_run_continuous_stops_when_rule_adds_no_new_label(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("ISSUE_NUMBER", "9")
    all_rules = engine.flatten_rules(engine.load_flows(str(p)), "m", "r")
    monkeypatch.setattr(run_rule, "_load_all_rules", lambda: all_rules)
    monkeypatch.setattr(run_steps, "current_subject_ref", lambda: SubjectRef("issue", "9"))

    labels = {"llmaw:start"}
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda ref, client: sorted(labels))

    executed = []

    def fake_execute(rule, client):
        executed.append(rule["id"])

    # rule a adds nothing (e.g. a plan PR opener with approved: {}) -> no new label
    monkeypatch.setattr(run_rule, "_execute_rule", fake_execute)

    run_rule._run_continuous([_matrix_for(p, "a")], FakeClient())
    assert executed == ["a"]


def test_run_continuous_pr_subject_runs_seed_without_looping(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("PR_NUMBER", "3")
    monkeypatch.setattr(
        run_steps, "current_subject_ref", lambda: SubjectRef("pull_request", "3")
    )
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda ref, client: ["llmaw:mid"])

    executed = []

    def fake_execute(rule, client):
        executed.append(rule["id"])

    monkeypatch.setattr(run_rule, "_execute_rule", fake_execute)
    # even though _load_all_rules would find a chain, PR subjects never loop
    monkeypatch.setattr(
        run_rule,
        "_load_all_rules",
        lambda: engine.flatten_rules(engine.load_flows(str(p)), "m", "r"),
    )

    run_rule._run_continuous([_matrix_for(p, "a")], FakeClient())
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
    monkeypatch.setattr(run_steps, "current_subject_ref", lambda: SubjectRef("issue", "1"))

    labels = {"llmaw:loop"}  # already seen, so re-adding won't look "new"
    # But we want a runaway: make each run add a fresh label that matches itself.
    # Use a counter so each iteration adds a distinct label matched by a rule
    # we inject via find_next. Easiest: monkeypatch find_next to always re-run.
    monkeypatch.setattr(engine, "find_next_rules", lambda rules, new: all_rules if new else [])
    monkeypatch.setattr(run_rule, "_fetch_labels", lambda ref, client: sorted(labels))

    executed = []
    counter = {"i": 0}

    def fake_execute(rule, client):
        executed.append(rule["id"])
        counter["i"] += 1
        labels.add(f"llmaw:tick-{counter['i']}")  # always something new

    monkeypatch.setattr(run_rule, "_execute_rule", fake_execute)

    run_rule._run_continuous([_matrix_for(p, "loop")], FakeClient())
    # cap is 2 iterations
    assert len(executed) == 2


def test_main_event_driven_runs_seed_once_even_if_labels_would_chain(monkeypatch, tmp_path):
    p = _write_flows(tmp_path, _CHAIN_FLOWS)
    monkeypatch.setenv("FLOWS_FILE", str(p))
    monkeypatch.setenv("MATCHED_RULE", "[]")  # will be overridden below via MATCHED_FILE
    monkeypatch.setenv("EXECUTION", "event-driven")
    monkeypatch.setenv("ISSUE_NUMBER", "5")
    monkeypatch.setattr(run_steps, "current_subject_ref", lambda: SubjectRef("issue", "5"))
    monkeypatch.setattr(run_rule, "_load_client", FakeClient)

    monkeypatch.setenv("MATCHED_FILE", str(tmp_path / "matched.json"))
    (tmp_path / "matched.json").write_text(json.dumps([_matrix_for(p, "a")]))

    executed = []

    def fake_execute(rule, client):
        executed.append(rule["id"])
        # pretend the agent advanced the state machine heavily
        labels = {"llmaw:mid", "llmaw:end"}
        monkeypatch.setattr(run_rule, "_fetch_labels", lambda ref, client: sorted(labels))

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
    monkeypatch.setenv("EXECUTION", "continuous")
    monkeypatch.setenv("ISSUE_NUMBER", "8")
    monkeypatch.setenv("MATCHED_FILE", str(tmp_path / "matched.json"))
    (tmp_path / "matched.json").write_text(json.dumps([_matrix_for(p, "a")]))
    monkeypatch.setattr(run_rule, "_load_client", FakeClient)

    called = {"continuous": False}

    def fake_continuous(seed, client):
        called["continuous"] = True
        return 0

    monkeypatch.setattr(run_rule, "_run_continuous", fake_continuous)
    assert run_rule.main() == 0
    assert called["continuous"] is True
