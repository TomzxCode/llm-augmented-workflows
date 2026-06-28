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
