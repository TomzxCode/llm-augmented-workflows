"""Unit tests for the local YAML-state tracker adapter."""

from __future__ import annotations

import pytest
import yaml

from llm_augmented_workflows.trackers import load_tracker
from llm_augmented_workflows.trackers.base import SubjectRef
from llm_augmented_workflows.trackers.local import LocalYamlClient


def _client(tmp_path) -> LocalYamlClient:
    return LocalYamlClient(tmp_path / "state")


def _read(tmp_path, name: str) -> dict:
    return yaml.safe_load((tmp_path / "state" / name).read_text())


def _write(tmp_path, name: str, data: dict) -> None:
    path = tmp_path / "state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


# --------------------------------------------------------------------------- #
# labels
# --------------------------------------------------------------------------- #
def test_missing_subject_file_reads_as_empty(tmp_path):
    assert _client(tmp_path).get_labels(SubjectRef("issue", "1")) == []


def test_add_labels_creates_file_on_first_mutation(tmp_path):
    client = _client(tmp_path)

    client.add_labels(SubjectRef("issue", "1"), ["llmaw:start"])

    data = _read(tmp_path, "issue-1.yml")
    assert data["labels"] == ["llmaw:start"]
    assert data["state"] == "open"
    assert data["comments"] == []


def test_add_labels_is_idempotent(tmp_path):
    client = _client(tmp_path)
    ref = SubjectRef("issue", "1")

    client.add_labels(ref, ["a"])
    client.add_labels(ref, ["a", "b"])

    assert client.get_labels(ref) == ["a", "b"]


def test_remove_labels(tmp_path):
    client = _client(tmp_path)
    ref = SubjectRef("issue", "1")
    client.add_labels(ref, ["a", "b"])

    client.remove_labels(ref, ["a"])

    assert client.get_labels(ref) == ["b"]


def test_file_name_hyphenates_pull_request_kind(tmp_path):
    client = _client(tmp_path)

    client.add_labels(SubjectRef("pull_request", "2"), ["x"])

    assert (tmp_path / "state" / "pull-request-2.yml").exists()


# --------------------------------------------------------------------------- #
# comment / close (write-only record)
# --------------------------------------------------------------------------- #
def test_comment_appends_to_subject_log(tmp_path):
    client = _client(tmp_path)
    ref = SubjectRef("issue", "1")

    client.comment(ref, "first")
    client.comment(ref, "second")

    comments = _read(tmp_path, "issue-1.yml")["comments"]
    assert [c["body"] for c in comments] == ["first", "second"]
    assert all(c["at"] for c in comments)


def test_close_sets_state_and_optionally_comments(tmp_path):
    client = _client(tmp_path)

    client.close(SubjectRef("issue", "1"), "done here")

    data = _read(tmp_path, "issue-1.yml")
    assert data["state"] == "closed"
    assert data["comments"][0]["body"] == "done here"


def test_close_without_comment(tmp_path):
    client = _client(tmp_path)

    client.close(SubjectRef("issue", "1"), None)

    data = _read(tmp_path, "issue-1.yml")
    assert data["state"] == "closed"
    assert data["comments"] == []


# --------------------------------------------------------------------------- #
# find_linked_subject
# --------------------------------------------------------------------------- #
def test_find_linked_subject_via_explicit_pointer(tmp_path):
    client = _client(tmp_path)
    _write(tmp_path, "issue-1.yml", {"labels": [], "state": "open", "comments": []})
    _write(
        tmp_path,
        "pull-request-2.yml",
        {"labels": [], "state": "open", "comments": [], "linked": "issue-1"},
    )

    ref = client.find_linked_subject(SubjectRef("pull_request", "2"))

    assert ref == SubjectRef("issue", "1")


def test_find_linked_subject_pointer_to_missing_issue_returns_none(tmp_path):
    client = _client(tmp_path)
    _write(
        tmp_path,
        "pull-request-2.yml",
        {"labels": [], "state": "open", "comments": [], "linked": "issue-9"},
    )

    assert client.find_linked_subject(SubjectRef("pull_request", "2")) is None


def test_find_linked_subject_via_title_env_regex(tmp_path, monkeypatch):
    client = _client(tmp_path)
    _write(tmp_path, "issue-1.yml", {"labels": [], "state": "open", "comments": []})
    monkeypatch.setenv("PR_TITLE", "Plan for issue #1")
    monkeypatch.delenv("PR_BODY", raising=False)
    _write(tmp_path, "pull-request-2.yml", {"labels": [], "state": "open", "comments": []})

    ref = client.find_linked_subject(SubjectRef("pull_request", "2"))

    assert ref == SubjectRef("issue", "1")


def test_find_linked_subject_regex_target_must_exist(tmp_path, monkeypatch):
    client = _client(tmp_path)
    monkeypatch.setenv("PR_TITLE", "Plan for issue #404")
    monkeypatch.delenv("PR_BODY", raising=False)

    assert client.find_linked_subject(SubjectRef("pull_request", "2")) is None


def test_find_linked_subject_none_without_pointer_or_env(tmp_path, monkeypatch):
    client = _client(tmp_path)
    monkeypatch.delenv("PR_TITLE", raising=False)
    monkeypatch.delenv("PR_BODY", raising=False)

    assert client.find_linked_subject(SubjectRef("pull_request", "2")) is None


# --------------------------------------------------------------------------- #
# sync_labels
# --------------------------------------------------------------------------- #
def test_sync_labels_writes_catalog(tmp_path):
    client = _client(tmp_path)
    defs = [{"name": "llmaw:bug", "description": "bug", "color": "D73A4A"}]

    client.sync_labels(defs)

    data = yaml.safe_load((tmp_path / "state" / "labels.yml").read_text())
    assert data == {"labels": defs}


# --------------------------------------------------------------------------- #
# load_tracker factory
# --------------------------------------------------------------------------- #
def test_factory_defaults_to_github():
    assert load_tracker({}).name == "github"


def test_factory_local_from_flows_config(tmp_path):
    client = load_tracker({"tracker": {"kind": "local", "state_dir": str(tmp_path / "s")}})

    assert isinstance(client, LocalYamlClient)
    assert client.state_dir == tmp_path / "s"


def test_factory_flows_config_beats_env(monkeypatch):
    monkeypatch.setenv("LLMAW_TRACKER", "local")

    assert load_tracker({"tracker": {"kind": "github"}}).name == "github"


def test_factory_env_fallback_when_config_silent(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLMAW_TRACKER", "local")

    client = load_tracker({})

    assert isinstance(client, LocalYamlClient)


def test_factory_unknown_kind_raises():
    with pytest.raises(ValueError):
        load_tracker({"tracker": {"kind": "linear"}})
