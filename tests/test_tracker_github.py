"""Unit tests for the GitHub tracker adapter (gh CLI + payload projection)."""

from __future__ import annotations

from llm_augmented_workflows.trackers import github
from llm_augmented_workflows.trackers.base import SubjectRef


def _capture_gh(monkeypatch, stdout=""):
    captured: dict = {}

    def fake_gh(args, *, capture=False):
        captured["args"] = args
        return stdout if capture else ""

    monkeypatch.setattr(github, "_gh", fake_gh)
    return captured


class _Proc:
    def __init__(self, rc):
        self.returncode = rc


# --------------------------------------------------------------------------- #
# labels
# --------------------------------------------------------------------------- #
def test_get_labels_issue(monkeypatch):
    captured = _capture_gh(monkeypatch, stdout="a\nb\n")
    client = github.GithubCliClient()

    assert client.get_labels(SubjectRef("issue", "7")) == ["a", "b"]
    assert captured["args"] == [
        "issue", "view", "7", "--json", "labels", "-q", ".labels[].name",
    ]


def test_get_labels_pr_uses_pr_subcommand(monkeypatch):
    captured = _capture_gh(monkeypatch, stdout="x\n")
    client = github.GithubCliClient()

    client.get_labels(SubjectRef("pull_request", "12"))

    assert captured["args"][0] == "pr"
    assert captured["args"][2] == "12"


def test_add_labels_joins_with_comma(monkeypatch):
    captured = _capture_gh(monkeypatch)
    client = github.GithubCliClient()

    client.add_labels(SubjectRef("issue", "7"), ["a", "b"])

    assert captured["args"] == ["issue", "edit", "7", "--add-label", "a,b"]


def test_remove_labels(monkeypatch):
    captured = _capture_gh(monkeypatch)
    client = github.GithubCliClient()

    client.remove_labels(SubjectRef("pull_request", "3"), ["x"])

    assert captured["args"] == ["pr", "edit", "3", "--remove-label", "x"]


# --------------------------------------------------------------------------- #
# comment / close (run-link footer owned by the client)
# --------------------------------------------------------------------------- #
def test_post_comment_appends_run_link(monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    captured = _capture_gh(monkeypatch)

    github.GithubCliClient().comment(SubjectRef("issue", "9"), "hello")

    assert captured["args"] == [
        "issue",
        "comment",
        "9",
        "--body",
        "hello\n\n---\n[Workflow run](https://github.com/owner/repo/actions/runs/12345)",
    ]


def test_post_comment_omits_link_without_run_env(monkeypatch):
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    captured = _capture_gh(monkeypatch)

    github.GithubCliClient().comment(SubjectRef("issue", "9"), "hello")

    assert captured["args"] == ["issue", "comment", "9", "--body", "hello"]


def test_close_with_comment_appends_run_link(monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    captured = _capture_gh(monkeypatch)

    github.GithubCliClient().close(SubjectRef("issue", "3"), "done")

    assert captured["args"] == [
        "issue",
        "close",
        "3",
        "--comment",
        "done\n\n---\n[Workflow run](https://github.com/owner/repo/actions/runs/77)",
    ]


def test_close_without_comment_posts_nothing(monkeypatch):
    captured = _capture_gh(monkeypatch)

    github.GithubCliClient().close(SubjectRef("issue", "3"), None)

    assert captured["args"] == ["issue", "close", "3"]


# --------------------------------------------------------------------------- #
# find_linked_subject (PR title/body env)
# --------------------------------------------------------------------------- #
def test_find_linked_subject_prefers_keyword_reference(monkeypatch):
    monkeypatch.setenv("PR_TITLE", "Plan for issue #42")
    monkeypatch.setenv("PR_BODY", "also mentions #99")

    ref = github.GithubCliClient().find_linked_subject(SubjectRef("pull_request", "7"))

    assert ref == SubjectRef("issue", "42")


def test_find_linked_subject_falls_back_to_any_ref(monkeypatch):
    monkeypatch.setenv("PR_TITLE", "")
    monkeypatch.setenv("PR_BODY", "see #13")

    ref = github.GithubCliClient().find_linked_subject(SubjectRef("pull_request", "7"))

    assert ref == SubjectRef("issue", "13")


def test_find_linked_subject_none_without_reference(monkeypatch):
    monkeypatch.setenv("PR_TITLE", "no refs here")
    monkeypatch.setenv("PR_BODY", "")

    assert github.GithubCliClient().find_linked_subject(SubjectRef("pull_request", "7")) is None


# --------------------------------------------------------------------------- #
# sync_labels (create, then edit when it already exists)
# --------------------------------------------------------------------------- #
def test_sync_labels_creates_when_absent(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Proc(0)

    monkeypatch.setattr(github.subprocess, "run", fake_run)

    github.GithubCliClient().sync_labels([{"name": "x", "description": "d", "color": "c"}])

    assert len(calls) == 1
    assert calls[0] == ["gh", "label", "create", "x", "--description", "d", "--color", "c"]


def test_sync_labels_edits_when_create_fails(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Proc(1) if len(calls) == 1 else _Proc(0)

    monkeypatch.setattr(github.subprocess, "run", fake_run)

    github.GithubCliClient().sync_labels([{"name": "x", "description": "d", "color": "c"}])

    assert len(calls) == 2
    assert calls[1] == ["gh", "label", "edit", "x", "--description", "d", "--color", "c"]


# --------------------------------------------------------------------------- #
# payload projection
# --------------------------------------------------------------------------- #
def test_from_github_payload_issue_labeled():
    ev = github.from_github_payload(
        "issues",
        {
            "action": "labeled",
            "label": {"name": "feature-request"},
            "issue": {"number": 5, "title": "Add dark mode", "body": "please"},
        },
    )

    assert ev.event == "issues"
    assert ev.action == "labeled"
    assert ev.subject == SubjectRef("issue", "5")
    assert ev.label == "feature-request"
    assert ev.title == "Add dark mode"
    assert ev.body == "please"
    assert ev.merged is None
    assert ev.branch is None


def test_from_github_payload_pr_closed():
    ev = github.from_github_payload(
        "pull_request",
        {
            "action": "closed",
            "pull_request": {
                "number": 9,
                "merged": True,
                "head": {"ref": "plan/issue-1"},
                "title": "Plan for issue #1",
                "body": "",
            },
        },
    )

    assert ev.subject == SubjectRef("pull_request", "9")
    assert ev.merged is True
    assert ev.branch == "plan/issue-1"


def test_from_github_payload_comment_types():
    payload = {"action": "created", "issue": {"number": 1}}
    payload["comment"] = {"user": {"login": "a"}, "body": "b"}
    general = github.from_github_payload("issue_comment", payload)
    inline = github.from_github_payload(
        "pull_request_review_comment",
        {
            "action": "created",
            "pull_request": {"number": 2},
            "comment": {"user": {"login": "a"}, "body": "b"},
        },
    )

    assert general.comment["type"] == "general"
    assert general.comment["author"] == "a"
    assert inline.comment["type"] == "inline"


def test_from_github_payload_without_subject():
    ev = github.from_github_payload("workflow_dispatch", {"action": None})

    assert ev.subject is None
    assert ev.action is None


# --------------------------------------------------------------------------- #
# event source
# --------------------------------------------------------------------------- #
def test_event_source_reads_actions_env(monkeypatch, tmp_path):
    payload = tmp_path / "event.json"
    payload.write_text('{"action": "labeled", "issue": {"number": 3}}')
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(payload))

    ev = github.GithubActionsEventSource().event()

    assert ev is not None
    assert ev.event == "issues"
    assert ev.subject == SubjectRef("issue", "3")


def test_event_source_returns_none_without_env(monkeypatch):
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    assert github.GithubActionsEventSource().event() is None
