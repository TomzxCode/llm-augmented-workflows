"""End-to-end tests for local mode: `llmaw trigger` and `llmaw run-rule`."""

from __future__ import annotations

import os

import pytest
import yaml

from llm_augmented_workflows import cli, run_rule

_ENV_KEYS = (
    "ISSUE_NUMBER",
    "ISSUE_TITLE",
    "ISSUE_BODY",
    "ISSUE_LABELS",
    "PR_NUMBER",
    "PR_TITLE",
    "PR_BODY",
    "PR_BRANCH",
    "PR_MERGED",
    "LABEL",
    "MATCHED_FILE",
    "MATCHED_RULE",
    "OUTCOME_YAML",
    "EXECUTION",
    "FLOWS_FILE",
)


@pytest.fixture(autouse=True)
def env_guard(monkeypatch):
    """Snapshot and restore the env the CLI mutates in-process."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)


def _flows(tmp_path, text: str) -> str:
    path = tmp_path / "flows.yml"
    path.write_text(text)
    return str(path)


def _state(tmp_path, name: str) -> dict:
    return yaml.safe_load((tmp_path / "state" / name).read_text())


def _write_state(tmp_path, name: str, data: dict) -> None:
    path = tmp_path / "state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


_CHAIN_FLOWS = """
tracker:
  kind: local
  state_dir: {state_dir}
flows:
  f:
    execution: continuous
    rules:
      - id: a
        when: {{event: issues, action: labeled, label: llmaw:start}}
        run: [{{labels: {{remove: [llmaw:start], add: [llmaw:mid]}}}}]
      - id: b
        when: {{event: issues, action: labeled, label: llmaw:mid}}
        run: [{{labels: {{remove: [llmaw:mid], add: [llmaw:end]}}}}]
"""


def test_trigger_runs_deterministic_chain_locally(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "FLOWS_FILE", _flows(tmp_path, _CHAIN_FLOWS.format(state_dir=tmp_path / "state"))
    )

    rc = cli.main(["trigger", "issues", "labeled", "--issue", "1", "--label", "llmaw:start"])

    assert rc == 0
    # llmaw:start was asserted into state, consumed by rule a, which chained to b.
    assert _state(tmp_path, "issue-1.yml")["labels"] == ["llmaw:end"]


def test_trigger_labeled_persists_label_when_no_rule_matches(tmp_path, monkeypatch):
    flows = """
tracker:
  kind: local
  state_dir: {state_dir}
flows:
  f:
    rules:
      - id: other
        when: {{event: issues, action: labeled, label: llmaw:unrelated}}
        run: [{{labels: {{add: [llmaw:x]}}}}]
"""
    monkeypatch.setenv(
        "FLOWS_FILE", _flows(tmp_path, flows.format(state_dir=tmp_path / "state"))
    )

    rc = cli.main(["trigger", "issues", "labeled", "--issue", "3", "--label", "llmaw:start"])

    assert rc == 0
    # no rule matched, but the labeled event still means the label is present
    assert _state(tmp_path, "issue-3.yml")["labels"] == ["llmaw:start"]


def test_trigger_synthetic_merge_relabels_linked_issue(tmp_path, monkeypatch):
    flows = """
tracker:
  kind: local
  state_dir: {state_dir}
flows:
  f:
    rules:
      - id: on-plan-merged
        when: {{event: pull_request, action: closed, merged: true, branch_prefix: plan/}}
        run:
          - labels: {{add: [llmaw:plan-approved], target: linked-issue}}
"""
    monkeypatch.setenv(
        "FLOWS_FILE", _flows(tmp_path, flows.format(state_dir=tmp_path / "state"))
    )
    _write_state(tmp_path, "issue-1.yml", {"labels": [], "state": "open", "comments": []})
    _write_state(
        tmp_path,
        "pull-request-2.yml",
        {"labels": [], "state": "open", "comments": [], "linked": "issue-1"},
    )

    rc = cli.main(
        [
            "trigger",
            "pull_request",
            "closed",
            "--pr",
            "2",
            "--merged",
            "--branch",
            "plan/issue-1",
        ]
    )

    assert rc == 0
    assert _state(tmp_path, "issue-1.yml")["labels"] == ["llmaw:plan-approved"]


def test_trigger_agent_outcome_relabels_and_comments(tmp_path, monkeypatch):
    flows = """
tracker:
  kind: local
  state_dir: {state_dir}
flows:
  f:
    rules:
      - id: triage
        when: {{event: issues, action: labeled, label: llmaw:triage}}
        run:
          - skill: triage-issue
          - on_outcome:
              feature: {{labels: {{add: [llmaw:feature-request]}}}}
              rejected: {{close: true, comment: wontfix, post_reason: true}}
"""
    monkeypatch.setenv(
        "FLOWS_FILE", _flows(tmp_path, flows.format(state_dir=tmp_path / "state"))
    )

    def fake_opencode(cmd, **kwargs):
        # The agent writes its verdict to $OUTCOME_YAML, as skills do.
        outcome = os.environ.get("OUTCOME_YAML")
        if outcome and "--command" in cmd:
            with open(outcome, "w") as fh:
                fh.write("verdict: feature\nreason: it is a feature\n")
        return type("Proc", (), {"returncode": 0})()

    monkeypatch.setattr(run_rule.subprocess, "run", fake_opencode)

    rc = cli.main(["trigger", "issues", "labeled", "--issue", "5", "--label", "llmaw:triage"])

    assert rc == 0
    data = _state(tmp_path, "issue-5.yml")
    assert "llmaw:feature-request" in data["labels"]


def test_trigger_requires_subject(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(
        "FLOWS_FILE", _flows(tmp_path, _CHAIN_FLOWS.format(state_dir=tmp_path / "state"))
    )

    with pytest.raises(SystemExit):
        cli.main(["trigger", "issues", "labeled", "--label", "llmaw:start"])


def test_run_rule_force_run_by_id(tmp_path, monkeypatch):
    flows = """
tracker:
  kind: local
  state_dir: {state_dir}
flows:
  f:
    rules:
      - id: tag-it
        when: {{event: issues, action: labeled, label: llmaw:go}}
        run: [{{labels: {{add: [llmaw:tagged]}}}}]
"""
    monkeypatch.setenv(
        "FLOWS_FILE", _flows(tmp_path, flows.format(state_dir=tmp_path / "state"))
    )

    rc = cli.main(["run-rule", "--rule-id", "tag-it", "--issue", "9"])

    assert rc == 0
    # the rule ran even though no labeled event fired (dry run)
    assert _state(tmp_path, "issue-9.yml")["labels"] == ["llmaw:tagged"]


def test_run_rule_unknown_rule_id_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(
        "FLOWS_FILE", _flows(tmp_path, _CHAIN_FLOWS.format(state_dir=tmp_path / "state"))
    )

    rc = cli.main(["run-rule", "--rule-id", "nope", "--issue", "1"])

    assert rc == 1
