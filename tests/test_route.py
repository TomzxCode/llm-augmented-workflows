"""Tests for the route module (event-to-rule matching)."""

from __future__ import annotations

import json
import textwrap

from llm_augmented_workflows.route import main as route_main


def _write_flows(tmp_path, text: str) -> str:
    p = tmp_path / "flows.yml"
    p.write_text(textwrap.dedent(text))
    return str(p)


def test_route_skips_stale_labeled_event(tmp_path, monkeypatch):
    """Regression test for issue #20: route skips rules whose trigger label
    is no longer present on the issue's live label set.

    This simulates a stale queued dispatch run: the event payload still
    carries the original trigger label, but the issue's live labels no
    longer contain it (because continuous mode consumed it).

    The route should return 0 matches for the stale event.
    """
    flows = _write_flows(
        tmp_path,
        """
        flows:
          f:
            rules:
              - id: r1
                when: {event: issues, action: labeled, label: llmaw:create-needs-assessment}
                run: [{skill: create-needs-assessment}]
        """,
    )
    monkeypatch.setenv("FLOWS_FILE", flows)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
    monkeypatch.setenv("MODEL", "test-model")
    monkeypatch.setenv("AGENTS_REPOSITORY", "test/agents")

    # Stale payload: label in event but removed from issue's live labels.
    event_payload = {
        "action": "labeled",
        "label": {"name": "llmaw:create-needs-assessment"},
        "issue": {"labels": []},
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event_payload))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    matched_file = tmp_path / "matched.json"
    monkeypatch.setenv("MATCHED_FILE", str(matched_file))

    assert route_main() == 0

    matched = json.loads(matched_file.read_text())
    assert len(matched) == 0, (
        f"Expected 0 matched rules (stale label filtered), got {len(matched)}."
    )


def test_route_matches_live_labeled_event(tmp_path, monkeypatch):
    """Verify that legitimate labeled events still match after the stale-label guard.

    When the trigger label is genuinely present on the issue, the route should
    match the rule normally.
    """
    flows = _write_flows(
        tmp_path,
        """
        flows:
          f:
            rules:
              - id: r1
                when: {event: issues, action: labeled, label: llmaw:create-needs-assessment}
                run: [{skill: create-needs-assessment}]
        """,
    )
    monkeypatch.setenv("FLOWS_FILE", flows)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
    monkeypatch.setenv("MODEL", "test-model")
    monkeypatch.setenv("AGENTS_REPOSITORY", "test/agents")

    # Live payload: trigger label is present on the issue.
    event_payload = {
        "action": "labeled",
        "label": {"name": "llmaw:create-needs-assessment"},
        "issue": {"labels": [{"name": "llmaw:create-needs-assessment"}]},
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event_payload))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    matched_file = tmp_path / "matched.json"
    monkeypatch.setenv("MATCHED_FILE", str(matched_file))

    assert route_main() == 0

    matched = json.loads(matched_file.read_text())
    assert len(matched) == 1, f"Expected 1 matched rule (live label), got {len(matched)}."
    assert matched[0]["id"] == "r1"
