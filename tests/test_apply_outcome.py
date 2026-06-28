"""Unit tests for apply_outcome comment posting (run-link footer)."""

from __future__ import annotations

from llm_augmented_workflows import apply_outcome


def _capture_gh(monkeypatch):
    captured: list[list[str]] = []

    def fake_gh(args, *, capture=False):
        captured.append(args)
        return ""

    monkeypatch.setattr(apply_outcome.run_steps, "_gh", fake_gh)
    return captured


def _write_outcome(monkeypatch, tmp_path, data: str):
    p = tmp_path / "outcome.yaml"
    p.write_text(data)
    monkeypatch.setenv("OUTCOME_YAML", str(p))
    return p


def _body_of(captured):
    """Extract the --body value from the first captured gh comment call."""
    args = captured[0]
    return args[args.index("--body") + 1]


def _comment_of(captured):
    """Extract the --comment value from the first captured gh close call."""
    args = captured[0]
    return args[args.index("--comment") + 1]


def test_post_comment_appends_run_link(monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    captured = _capture_gh(monkeypatch)

    apply_outcome._post_comment(9, "issue", "hello")

    assert captured == [
        [
            "issue",
            "comment",
            "9",
            "--body",
            "hello\n\n---\n[Workflow run](https://github.com/owner/repo/actions/runs/12345)",
        ]
    ]


def test_post_comment_omits_link_without_run_env(monkeypatch):
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    captured = _capture_gh(monkeypatch)

    apply_outcome._post_comment(9, "issue", "hello")

    assert captured == [["issue", "comment", "9", "--body", "hello"]]


def test_close_with_comment_appends_run_link(monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    captured = _capture_gh(monkeypatch)

    apply_outcome._close(3, "issue", "done")

    assert captured == [
        [
            "issue",
            "close",
            "3",
            "--comment",
            "done\n\n---\n[Workflow run](https://github.com/owner/repo/actions/runs/77)",
        ]
    ]


def test_close_without_comment_posts_nothing(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    captured = _capture_gh(monkeypatch)

    apply_outcome._close(3, "issue", None)

    assert captured == [["issue", "close", "3"]]


# --------------------------------------------------------------------------- #
# post_reason gates whether the outcome reason surfaces as a comment
# --------------------------------------------------------------------------- #


def test_post_reason_uses_outcome_reason_for_close(monkeypatch, tmp_path):
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: rejected\nreason: The request is out of scope for v2.\n",
    )
    captured = _capture_gh(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "rejected": {"close": True, "comment": "Closing as wontfix.", "post_reason": True},
            },
            "default": None,
        }
    )

    assert _comment_of(captured) == "The request is out of scope for v2."


def test_post_reason_falls_back_to_action_comment(monkeypatch, tmp_path):
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(monkeypatch, tmp_path, "verdict: rejected\nreason: ''\n")
    captured = _capture_gh(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "rejected": {"close": True, "comment": "Closing as wontfix.", "post_reason": True},
            },
            "default": None,
        }
    )

    assert _comment_of(captured) == "Closing as wontfix."


def test_post_reason_uses_outcome_reason_for_standalone(monkeypatch, tmp_path):
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: needs-info\nreason: Please clarify the target platform.\n",
    )
    captured = _capture_gh(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "needs-info": {"comment": "Need more information.", "post_reason": True},
            },
            "default": None,
        }
    )

    assert captured[0][:3] == ["issue", "comment", "42"]
    assert _body_of(captured) == "Please clarify the target platform."


def test_without_post_reason_ignores_outcome_reason(monkeypatch, tmp_path):
    """An action without post_reason posts its hardcoded comment, not the reason."""
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: needs-info\nreason: Please clarify the target platform.\n",
    )
    captured = _capture_gh(monkeypatch)

    apply_outcome.apply(
        {
            "cases": {
                "needs-info": {"comment": "Need more information."},
            },
            "default": None,
        }
    )

    assert _body_of(captured) == "Need more information."


def test_label_only_action_stays_silent_with_reason_present(monkeypatch, tmp_path):
    """A label-only action (no comment, no post_reason) posts nothing."""
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: approved\nreason: Everything looks good.\n",
    )
    captured = _capture_gh(monkeypatch)
    # swallow label edits so captured only holds comment/close calls
    monkeypatch.setattr(apply_outcome.run_steps, "apply_labels", lambda step: None)

    apply_outcome.apply(
        {
            "cases": {
                "approved": {"labels": {"add": ["llmaw:approved"]}},
            },
            "default": None,
        }
    )

    assert captured == []


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
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    _write_outcome(
        monkeypatch,
        tmp_path,
        "verdict: changes-requested\nreason: Missing rollback strategy.\n",
    )
    captured = _capture_gh(monkeypatch)
    monkeypatch.setattr(apply_outcome.run_steps, "apply_labels", lambda step: None)

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

    apply_outcome.apply(on_outcome)

    assert _body_of(captured) == "Missing rollback strategy."
