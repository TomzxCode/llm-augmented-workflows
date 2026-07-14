"""Unit tests for the routing/steps engine (engine.py)."""

from __future__ import annotations

import textwrap

import pytest

from llm_augmented_workflows.engine import (
    AgentStep,
    ConfigError,
    When,
    build_agent,
    compute_label_diff,
    find_next_rules,
    flatten_rules,
    load_flows,
    matches,
    normalize_action,
    normalize_label_step,
    normalize_on_outcome,
    normalize_run,
    normalize_shell_step,
    parse_execution,
    parse_when,
    resolve_dispatch_execution,
    resolve_execution_for_flow,
    rule_to_matrix,
    split_steps,
)


def write_flows(tmp_path, text: str):
    p = tmp_path / "flows.yml"
    p.write_text(textwrap.dedent(text))
    return str(p)


# --------------------------------------------------------------------------- #
# normalize_run / split_steps
# --------------------------------------------------------------------------- #
def test_normalize_run_wraps_single_dict():
    assert normalize_run({"skill": "x"}) == [{"skill": "x"}]


def test_normalize_run_rejects_multi_key_step():
    with pytest.raises(ConfigError):
        normalize_run([{"skill": "x", "labels": {"add": ["y"]}}])


def test_normalize_run_rejects_unknown_kind():
    with pytest.raises(ConfigError):
        normalize_run([{"bogus": "x"}])


def test_split_steps_pre_deterministic_before_agent():
    pre, agent, post, oc = split_steps(
        normalize_run(
            [
                {"labels": {"add": ["a"]}},
                {"shell": "s.sh"},
                {"skill": "x"},
            ]
        )
    )
    assert [next(iter(d)) for d in pre] == ["labels", "shell"]
    assert next(iter(agent)) == "skill"
    assert post == []
    assert oc is None


def test_split_steps_deterministic_after_agent_is_post():
    # labels/shell may appear on either side of the agent
    pre, agent, post, oc = split_steps(
        normalize_run(
            [
                {"skill": "x"},
                {"labels": {"remove": ["a"]}},
            ]
        )
    )
    assert pre == []
    assert next(iter(agent)) == "skill"
    assert [next(iter(s)) for s in post] == ["labels"]
    assert oc is None


def test_split_steps_pre_agent_post_outcome():
    pre, agent, post, oc = split_steps(
        normalize_run(
            [
                {"labels": {"add": ["pre"]}},
                {"skill": "x"},
                {"labels": {"remove": ["post"]}},
                {"on_outcome": {"approved": {"labels": {"add": ["b"]}}}},
            ]
        )
    )
    assert [next(iter(s)) for s in pre] == ["labels"]
    assert next(iter(agent)) == "skill"
    assert [next(iter(s)) for s in post] == ["labels"]
    assert next(iter(oc)) == "on_outcome"


def test_split_steps_rejects_deterministic_after_on_outcome():
    with pytest.raises(ConfigError):
        split_steps(
            normalize_run(
                [
                    {"skill": "x"},
                    {"on_outcome": {"approved": {"labels": {"add": ["a"]}}}},
                    {"labels": {"add": ["b"]}},
                ]
            )
        )


def test_split_steps_rejects_on_outcome_before_agent():
    with pytest.raises(ConfigError):
        split_steps(normalize_run([{"on_outcome": {"approved": {"labels": {"add": ["a"]}}}}]))


def test_split_steps_rejects_two_on_outcome_steps():
    with pytest.raises(ConfigError):
        split_steps(
            normalize_run(
                [
                    {"skill": "x"},
                    {"on_outcome": {"approved": {"labels": {"add": ["a"]}}}},
                    {"on_outcome": {"approved": {"labels": {"add": ["b"]}}}},
                ]
            )
        )


def test_split_steps_rejects_two_agent_steps():
    with pytest.raises(ConfigError):
        split_steps(normalize_run([{"skill": "x"}, {"prompt": "p.md"}]))


# --------------------------------------------------------------------------- #
# build_agent resolution precedence
# --------------------------------------------------------------------------- #
def test_build_agent_precedence():
    step = {"skill": "x"}
    # base only
    a = build_agent(step, {}, "base-model", "base-repo")
    assert a == AgentStep("skill", "x", "base-model", "base-repo")
    # defaults override base
    a = build_agent(step, {"model": "def-model", "agents_repository": "def-repo"}, "base", "base")
    assert a.model == "def-model" and a.agents_repository == "def-repo"
    # step override wins
    step = {"skill": {"name": "x", "model": "over-model", "agents_repository": "over-repo"}}
    a = build_agent(step, {"model": "def"}, "base", "base")
    assert a.model == "over-model" and a.agents_repository == "over-repo"


def test_build_agent_prompt_kind():
    a = build_agent({"prompt": ".agents/commands/x.md"}, {}, "m", "r")
    assert a.kind == "prompt" and a.ref == ".agents/commands/x.md"


# --------------------------------------------------------------------------- #
# matches
# --------------------------------------------------------------------------- #
def test_matches_event_and_action():
    when = parse_when({"event": "issues", "action": "labeled"})
    assert matches(when, "issues", {"action": "labeled"})
    assert not matches(when, "issues", {"action": "opened"})
    assert not matches(when, "pull_request", {"action": "labeled"})


def test_matches_label():
    when = parse_when({"event": "issues", "action": "labeled", "label": "plan-needed"})
    assert matches(when, "issues", {"action": "labeled", "label": {"name": "plan-needed"}})
    assert not matches(when, "issues", {"action": "labeled", "label": {"name": "other"}})


def test_matches_merged_and_branch_prefix():
    when = parse_when(
        {"event": "pull_request", "action": "closed", "merged": True, "branch_prefix": "plan/"}
    )
    payload = {
        "action": "closed",
        "pull_request": {"merged": True, "head": {"ref": "plan/issue-1"}},
    }
    assert matches(when, "pull_request", payload)
    bad = {"action": "closed", "pull_request": {"merged": False, "head": {"ref": "plan/x"}}}
    assert not matches(when, "pull_request", bad)
    other = {"action": "closed", "pull_request": {"merged": True, "head": {"ref": "impl/x"}}}
    assert not matches(when, "pull_request", other)


def test_matches_body_contains():
    when = parse_when(
        {"event": "issue_comment", "action": "created", "body_contains": "Plan for issue"}
    )
    assert matches(
        when, "issue_comment", {"action": "created", "issue": {"body": "Plan for issue #4"}}
    )
    assert not matches(when, "issue_comment", {"action": "created", "issue": {"body": "hello"}})


def test_matches_unspecified_fields_are_wildcards():
    when = When()  # match everything
    assert matches(when, "issues", {"action": "opened"})


def test_matches_labeled_event_uses_payload_not_live_labels():
    """matches() keys on the event payload label, not the issue's live labels.

    This is the root cause of the redundant dispatch cascade described in
    issue #20: a stale queued dispatch run whose trigger label was already
    consumed by continuous mode still matches because the payload still
    carries the original label name. matches() has no access to live label
    state.
    """
    when = parse_when(
        {"event": "issues", "action": "labeled", "label": "llmaw:create-needs-assessment"}
    )
    # Payload carries the label that triggered the event (even if it was
    # later removed by continuous mode before this dispatch run starts).
    payload = {"action": "labeled", "label": {"name": "llmaw:create-needs-assessment"}}
    assert matches(when, "issues", payload)

    # matches() returns True even though the label is stale/unchecked
    # against live state. The responsibility for staleness checking lies
    # in the caller (route.py), not in the pure matching function.


# --------------------------------------------------------------------------- #
# flatten_rules end to end
# --------------------------------------------------------------------------- #
def test_flatten_rules_and_matrix(tmp_path):
    path = write_flows(
        tmp_path,
        """
        defaults:
          model: default-model
          agents_repository: default-repo
          timeout_minutes: 30
        flows:
          plan:
            rules:
              - id: triage
                when: {event: issues, action: labeled, label: feature-request}
                run:
                  - labels: {remove: [feature-request], add: [triaged]}
                  - skill: triage-feature
              - id: relabel
                when: {event: pull_request, action: closed, merged: true, branch_prefix: plan/}
                run:
                  - labels: {add: [plan-approved], target: linked-issue}
        """,
    )
    rules = flatten_rules(load_flows(path), "base-model", "base-repo")
    assert [r.id for r in rules] == ["triage", "relabel"]

    triage = next(r for r in rules if r.id == "triage")
    assert triage.flow == "plan"
    assert triage.agent is not None and triage.agent.model == "default-model"
    m = rule_to_matrix(triage)
    assert m["has_deterministic"] is True and m["has_agent"] is True
    assert m["deterministic"][0] == {
        "labels": {"add": ["triaged"], "remove": ["feature-request"], "target": "subject"}
    }
    assert m["agent"]["kind"] == "skill" and m["agent"]["ref"] == "triage-feature"

    relabel = next(r for r in rules if r.id == "relabel")
    mr = rule_to_matrix(relabel)
    assert mr["has_agent"] is False
    assert mr["deterministic"][0]["labels"]["target"] == "linked-issue"


def test_flatten_rules_rejects_rule_without_steps(tmp_path):
    path = write_flows(
        tmp_path,
        """
        flows:
          f:
            rules:
              - id: empty
                when: {event: issues}
        """,
    )
    with pytest.raises(ConfigError):
        flatten_rules(load_flows(path), "m", "r")


# --------------------------------------------------------------------------- #
# normalize_label_step / compute_label_diff
# --------------------------------------------------------------------------- #
def test_normalize_label_step_coerces_strings():
    out = normalize_label_step({"labels": {"add": "a", "remove": "b"}})
    assert out["labels"]["add"] == ["a"]
    assert out["labels"]["remove"] == ["b"]
    assert out["labels"]["target"] == "subject"


def test_normalize_label_step_rejects_bad_target():
    with pytest.raises(ConfigError):
        normalize_label_step({"labels": {"target": "nowhere"}})


# --------------------------------------------------------------------------- #
# normalize_shell_step
# --------------------------------------------------------------------------- #
def test_normalize_shell_step_string_form():
    assert normalize_shell_step({"shell": "s.sh"}) == {"shell": {"run": "s.sh", "args": []}}


def test_normalize_shell_step_list_form_with_args():
    out = normalize_shell_step({"shell": ["s.sh", "a", "b"]})
    assert out == {"shell": {"run": "s.sh", "args": ["a", "b"]}}


def test_normalize_shell_step_list_coerces_args_to_strings():
    out = normalize_shell_step({"shell": ["s.sh", 5, True]})
    assert out["shell"]["args"] == ["5", "True"]


def test_normalize_shell_step_rejects_empty_list():
    with pytest.raises(ConfigError):
        normalize_shell_step({"shell": []})


def test_normalize_shell_step_rejects_non_string_script():
    with pytest.raises(ConfigError):
        normalize_shell_step({"shell": [5, "a"]})


def test_normalize_shell_step_rejects_dict_form():
    # only string and list (argv) are supported; dict is not
    with pytest.raises(ConfigError):
        normalize_shell_step({"shell": {"run": "s.sh"}})


def test_shell_args_threads_through_matrix(tmp_path):
    path = write_flows(
        tmp_path,
        """
        flows:
          f:
            rules:
              - id: r
                when: {event: issues, action: labeled, label: llmaw:x}
                run:
                  - skill: create-x
                  - shell: [.github/llmaw/scripts/commit-sdlc.sh, "draft x"]
        """,
    )
    r = flatten_rules(load_flows(path), "m", "r")[0]
    m = rule_to_matrix(r)
    step = m["post_deterministic"][0]["shell"]
    assert step["run"] == ".github/llmaw/scripts/commit-sdlc.sh"
    assert step["args"] == ["draft x"]


def test_compute_label_diff_is_idempotent():
    current = ["a", "b"]
    add, remove = compute_label_diff(current, ["a", "c"], ["b", "z"])
    assert add == ["c"]
    assert remove == ["b"]


def test_parse_when_coerces_merged():
    assert parse_when({"merged": True}).merged is True
    assert parse_when({"merged": False}).merged is False
    assert parse_when({}).merged is None


# --------------------------------------------------------------------------- #
# execution mode
# --------------------------------------------------------------------------- #
def test_parse_execution_accepts_known_and_defaults():
    assert parse_execution(None) == "event-driven"
    assert parse_execution("continuous") == "continuous"
    assert parse_execution("  Event-Driven ") == "event-driven"


def test_parse_execution_rejects_unknown():
    with pytest.raises(ConfigError):
        parse_execution("async")
    with pytest.raises(ConfigError):
        parse_execution(5)


def test_resolve_execution_for_flow_precedence():
    raw = {
        "defaults": {"execution": "continuous"},
        "flows": {
            "a": {"execution": "event-driven"},
            "b": {},
            "c": {"execution": "continuous"},
        },
    }
    # flow override beats defaults
    assert resolve_execution_for_flow(raw, "a", None) == "event-driven"
    # defaults apply when flow is silent
    assert resolve_execution_for_flow(raw, "b", None) == "continuous"
    # explicit flow continuous
    assert resolve_execution_for_flow(raw, "c", None) == "continuous"
    # forced override beats everything
    assert resolve_execution_for_flow(raw, "a", "continuous") == "continuous"
    assert resolve_execution_for_flow(raw, "c", "event-driven") == "event-driven"
    # missing flow falls back to defaults
    assert resolve_execution_for_flow(raw, "missing", None) == "continuous"


def test_resolve_dispatch_execution_continuous_wins_and_override_forces():
    raw = {"flows": {"a": {"execution": "event-driven"}, "b": {"execution": "continuous"}}}
    ra = type("R", (), {"flow": "a"})()
    rb = type("R", (), {"flow": "b"})()
    # mixed -> continuous
    assert resolve_dispatch_execution(raw, [ra, rb], None) == "continuous"
    # all event-driven -> event-driven
    assert resolve_dispatch_execution(raw, [ra], None) == "event-driven"
    # override forces regardless
    assert resolve_dispatch_execution(raw, [rb], "event-driven") == "event-driven"
    # no rules -> event-driven
    assert resolve_dispatch_execution(raw, [], None) == "event-driven"


# --------------------------------------------------------------------------- #
# find_next_rules (continuous chaining)
# --------------------------------------------------------------------------- #
def _rules_from(text: str, tmp_path):
    path = write_flows(tmp_path, text)
    return flatten_rules(load_flows(path), "m", "r")


def test_find_next_rules_matches_new_labels(tmp_path):
    rules = _rules_from(
        """
        flows:
          f:
            rules:
              - id: needs-create
                when: {event: issues, action: labeled, label: llmaw:feature-request}
                run: [{skill: x}]
              - id: needs-review
                when: {event: issues, action: labeled, label: llmaw:review-needs}
                run: [{skill: y}]
              - id: on-merge
                when: {event: pull_request, action: closed, merged: true}
                run: [{labels: {add: [llmaw:plan-approved]}}]
        """,
        tmp_path,
    )
    nxt = find_next_rules(rules, ["llmaw:feature-request"])
    assert [r.id for r in nxt] == ["needs-create"]
    # empty new_labels short-circuits
    assert find_next_rules(rules, []) == []


def test_find_next_rules_skips_non_issue_and_event_agnostic(tmp_path):
    rules = _rules_from(
        """
        flows:
          f:
            rules:
              - id: pr-merge
                when: {event: pull_request, action: closed, label: llmaw:x}
                run: [{labels: {add: [llmaw:y]}}]
              - id: opened
                when: {event: issues, action: opened}
                run: [{skill: z}]
              - id: labeled-x
                when: {event: issues, action: labeled, label: llmaw:x}
                run: [{skill: q}]
        """,
        tmp_path,
    )
    # PR rule and event-agnostic opened rule are never chained
    nxt = find_next_rules(rules, ["llmaw:x"])
    assert [r.id for r in nxt] == ["labeled-x"]


# --------------------------------------------------------------------------- #
# on_outcome normalization
# --------------------------------------------------------------------------- #
def test_normalize_action_coerces_and_defaults():
    a = normalize_action({"labels": {"add": "x", "remove": "y"}}, "k")
    assert a["labels"]["add"] == ["x"] and a["labels"]["remove"] == ["y"]
    assert a["labels"]["target"] == "subject"
    assert a["close"] is False and a["comment"] is None
    assert a["post_reason"] is False
    empty = normalize_action(None, "k")
    assert empty == {
        "labels": {"add": [], "remove": [], "target": "subject"},
        "close": False,
        "comment": None,
        "post_reason": False,
    }


def test_normalize_action_preserves_post_reason():
    a = normalize_action({"comment": "fallback", "post_reason": True}, "k")
    assert a["post_reason"] is True


def test_normalize_action_rejects_bad_fields():
    with pytest.raises(ConfigError):
        normalize_action({"labels": {"target": "bogus"}}, "k")
    with pytest.raises(ConfigError):
        normalize_action({"labels": "not a mapping"}, "k")
    with pytest.raises(ConfigError):
        normalize_action({"close": "yes"}, "k")
    with pytest.raises(ConfigError):
        normalize_action({"comment": 5}, "k")
    with pytest.raises(ConfigError):
        normalize_action({"post_reason": "yes"}, "k")


def test_normalize_on_outcome_cases_and_default():
    out = normalize_on_outcome(
        {"on_outcome": {"approved": {"labels": {"add": ["x"]}}, "_": {"comment": "fallback"}}}
    )
    assert set(out["cases"]) == {"approved"}
    assert out["cases"]["approved"]["labels"]["add"] == ["x"]
    assert out["default"]["comment"] == "fallback"


def test_normalize_on_outcome_rejects_non_mapping():
    with pytest.raises(ConfigError):
        normalize_on_outcome({"on_outcome": "oops"})
    with pytest.raises(ConfigError):
        normalize_on_outcome({"on_outcome": {}})


def test_normalize_on_outcome_needs_a_verdict_case():
    with pytest.raises(ConfigError):
        normalize_on_outcome({"on_outcome": {"_": {"comment": "only default"}}})


# --------------------------------------------------------------------------- #
# on_outcome end to end
# --------------------------------------------------------------------------- #
def test_on_outcome_threaded_through_matrix(tmp_path):
    path = write_flows(
        tmp_path,
        """
        flows:
          f:
            rules:
              - id: r
                when: {event: issues, action: labeled, label: llmaw:feature-request}
                run:
                  - skill: create-needs-assessment
                  - on_outcome:
                      approved: {labels: {add: [llmaw:needs-approved]}}
                      rejected: {close: true, comment: wontfix}
                      needs-info: {labels: {add: [llmaw:needs-info]}}
                      _: {comment: "no verdict"}
        """,
    )
    rules = flatten_rules(load_flows(path), "m", "r")
    assert len(rules) == 1
    r = rules[0]
    assert r.agent is not None and r.on_outcome is not None
    cases = r.on_outcome["cases"]
    assert set(cases) == {"approved", "rejected", "needs-info"}
    assert cases["approved"]["labels"]["add"] == ["llmaw:needs-approved"]
    assert cases["rejected"]["close"] is True
    assert cases["rejected"]["comment"] == "wontfix"
    assert r.on_outcome["default"]["comment"] == "no verdict"
    m = rule_to_matrix(r)
    assert m["has_on_outcome"] is True
    assert m["on_outcome"]["cases"]["needs-info"]["labels"]["add"] == ["llmaw:needs-info"]


def test_post_deterministic_threaded_through_matrix(tmp_path):
    path = write_flows(
        tmp_path,
        """
        flows:
          f:
            rules:
              - id: r
                when: {event: issues, action: labeled, label: llmaw:review-x}
                run:
                  - skill: review-x
                  - labels: {remove: [llmaw:review-x]}
                  - on_outcome:
                      approved: {labels: {add: [llmaw:x-approved]}}
        """,
    )
    r = flatten_rules(load_flows(path), "m", "r")[0]
    assert r.deterministic == []  # nothing pre-agent
    assert [next(iter(s)) for s in r.post_deterministic] == ["labels"]
    m = rule_to_matrix(r)
    assert m["has_deterministic"] is False
    assert m["has_post_deterministic"] is True
    assert m["post_deterministic"][0] == {
        "labels": {"add": [], "remove": ["llmaw:review-x"], "target": "subject"}
    }
