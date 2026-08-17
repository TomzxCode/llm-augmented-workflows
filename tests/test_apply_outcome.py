"""Unit tests for apply_outcome (verdict routing, post_reason, notice path)."""

from __future__ import annotations

from llm_augmented_workflows import apply_outcome
from llm_augmented_workflows.trackers.base import SubjectRef


class FakeClient:
    name = "fake"

    def __init__(self):
        self.calls: list[tuple] = []

    def get_labels(self, ref):
        return []

    def add_labels(self, ref, labels):
        self.calls.append(("add_labels", ref, list(labels)))

    def remove_labels(self, ref, labels):
        self.calls.append(("remove_labels", ref, list(labels)))

    def comment(self, ref, body):
        self.calls.append(("comment", ref, body))

    def close(self, ref, comment):
        self.calls.append(("close", ref, comment))

    def find_linked_subject(self, ref):
        return None

    def sync_labels(self, defs):
        self.calls.append(("sync_labels", defs))


def _client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(apply_outcome.run_steps, "apply_labels", lambda step, c=None: None)
    return client


def _write_outcome(monkeypatch, tmp_path, data: str):
    p = tmp_path / "outcome.yaml"
    p.write_text(data)
    monkeypatch.setenv("OUTCOME_YAML", str(p))
    return p


def _body_of(client):
    """Extract the body from the first recorded comment call."""
    return next(call[2] for call in client.calls if call[0] == "comment")


def _comment_of(client):
    """Extract the comment from the first recorded close call."""
    return next(call[2] for call in client.calls if call[0] == "close")


def _comment_calls(client):
    return [call for call in client.calls if call[0] in ("comment", "close")]


# --------------------------------------------------------------------------- #
# close / comment routing
# --------------------------------------------------------------------------- #
def test_close_with_comment(monkeypatch, tmp_path):
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(monkeypatch, tmp_path, "verdict: rejected\nreason: r\n")
    client = _client(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "rejected": {"close": True, "comment": "Closing as wontfix."},
            },
            "default": None,
        },
        client=client,
    )

    assert client.calls == [
        ("close", SubjectRef("issue", "42"), "Closing as wontfix.")
    ]


def test_close_without_comment_posts_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(monkeypatch, tmp_path, "verdict: rejected\nreason: r\n")
    client = _client(monkeypatch)

    apply_outcome.apply(
        {"cases": {"rejected": {"close": True}}, "default": None},
        client=client,
    )

    assert client.calls == [("close", SubjectRef("issue", "42"), None)]


# --------------------------------------------------------------------------- #
# post_reason gates whether the outcome reason surfaces as a comment
# --------------------------------------------------------------------------- #


def test_post_reason_uses_outcome_reason_for_close(monkeypatch, tmp_path):
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: rejected\nreason: The request is out of scope for v2.\n",
    )
    client = _client(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "rejected": {"close": True, "comment": "Closing as wontfix.", "post_reason": True},
            },
            "default": None,
        },
        client=client,
    )

    assert _comment_of(client) == "The request is out of scope for v2."


def test_post_reason_falls_back_to_action_comment(monkeypatch, tmp_path):
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(monkeypatch, tmp_path, "verdict: rejected\nreason: ''\n")
    client = _client(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "rejected": {"close": True, "comment": "Closing as wontfix.", "post_reason": True},
            },
            "default": None,
        },
        client=client,
    )

    assert _comment_of(client) == "Closing as wontfix."


def test_post_reason_uses_outcome_reason_for_standalone(monkeypatch, tmp_path):
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: needs-info\nreason: Please clarify the target platform.\n",
    )
    client = _client(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "needs-info": {"comment": "Need more information.", "post_reason": True},
            },
            "default": None,
        },
        client=client,
    )

    assert client.calls[0][0] == "comment"
    assert client.calls[0][1] == SubjectRef("issue", "42")
    assert _body_of(client) == "Please clarify the target platform."


def test_without_post_reason_ignores_outcome_reason(monkeypatch, tmp_path):
    """An action without post_reason posts its hardcoded comment, not the reason."""
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: needs-info\nreason: Please clarify the target platform.\n",
    )
    client = _client(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "needs-info": {"comment": "Need more information."},
            },
            "default": None,
        },
        client=client,
    )

    assert _body_of(client) == "Need more information."


def test_label_only_action_stays_silent_with_reason_present(monkeypatch, tmp_path):
    """A label-only action (no comment, no post_reason) posts nothing."""
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: approved\nreason: Everything looks good.\n",
    )
    client = _client(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "approved": {"labels": {"add": ["llmaw:approved"]}},
            },
            "default": None,
        },
        client=client,
    )

    assert _comment_calls(client) == []


def test_no_case_and_no_default_posts_notice(monkeypatch, tmp_path):
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(monkeypatch, tmp_path, "verdict: approved\nreason: r\n")
    client = _client(monkeypatch)

    apply_outcome.apply(
        {"cases": {"rejected": {"close": True}}, "default": None},
        client=client,
    )

    assert len(_comment_calls(client)) == 1
    assert "verdict: approved" in _body_of(client)


def test_default_case_used_when_verdict_unmatched(monkeypatch, tmp_path):
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(monkeypatch, tmp_path, "verdict: unknown\nreason: r\n")
    client = _client(monkeypatch)

    apply_outcome.apply(
        {"cases": {"rejected": {"close": True}}, "default": {"comment": "fallback"}},
        client=client,
    )

    assert _body_of(client) == "fallback"


def test_without_subject_close_comment_skipped(monkeypatch, tmp_path):
    monkeypatch.delenv("ISSUE_NUMBER", raising=False)
    monkeypatch.delenv("PR_NUMBER", raising=False)
    _write_outcome(monkeypatch, tmp_path, "verdict: rejected\nreason: r\n")
    client = _client(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {"rejected": {"close": True, "comment": "bye"}},
            "default": None,
        },
        client=client,
    )

    assert client.calls == []


# --------------------------------------------------------------------------- #
# outcome_present requires both verdict and reason
# --------------------------------------------------------------------------- #


def test_outcome_present_true_with_verdict_and_reason(monkeypatch, tmp_path):
    _write_outcome(monkeypatch, tmp_path, "verdict: approved\nreason: looks good\n")
    assert apply_outcome.outcome_present() is True


def test_outcome_present_false_when_reason_missing(monkeypatch, tmp_path):
    _write_outcome(monkeypatch, tmp_path, "verdict: approved\n")
    assert apply_outcome.outcome_present() is False


def test_outcome_present_false_when_verdict_missing(monkeypatch, tmp_path):
    _write_outcome(monkeypatch, tmp_path, "reason: some reason\n")
    assert apply_outcome.outcome_present() is False


def test_outcome_present_false_when_file_missing(monkeypatch):
    monkeypatch.delenv("OUTCOME_YAML", raising=False)
    assert apply_outcome.outcome_present() is False


# --------------------------------------------------------------------------- #
# Regression: post_reason declared in flows.yml must survive normalization
# and reach apply() so the skill's reason is posted instead of the fallback.
# --------------------------------------------------------------------------- #


def test_post_reason_survives_normalize_to_apply(monkeypatch, tmp_path):
    """End-to-end: normalize_on_outcome -> apply posts the skill's reason.

    This exercises the path the per-action unit tests bypass by handing apply()
    a pre-built dict. Previously normalize_action dropped ``post_reason``, so
    the hardcoded comment was posted and the reason discarded.
    """
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: changes-requested\nreason: Missing rollback strategy.\n",
    )
    client = _client(monkeypatch)

    from llm_augmented_workflows.engine import normalize_on_outcome

    on_outcome = normalize_on_outcome(
        {
            "on_outcome": {
                "changes-requested": {
                    "labels": {"add": ["llmaw:revise"]},
                    "comment": "Fallback comment.",
                    "post_reason": True,
                }
            }
        }
    )

    apply_outcome.apply(on_outcome, client=client)

    assert _body_of(client) == "Missing rollback strategy."
