"""Unit tests for label migration planning and per-tracker rename behavior."""

from __future__ import annotations

import pytest

from llm_augmented_workflows.engine import ConfigError
from llm_augmented_workflows.trackers import base, github, local


def test_plan_migrations_renames_existing_old_to_new():
    declared = [{"name": "llmaw:new", "migrate_from": ["llmaw:old"]}]
    renames, conflicts = base.plan_label_migrations(declared, {"llmaw:old"})
    assert renames == [("llmaw:old", "llmaw:new")]
    assert conflicts == []


def test_plan_migrations_skips_when_old_absent():
    declared = [{"name": "llmaw:new", "migrate_from": ["llmaw:old"]}]
    renames, conflicts = base.plan_label_migrations(declared, {"other"})
    assert renames == []
    assert conflicts == []


def test_plan_migrations_conflicts_when_target_already_exists():
    declared = [{"name": "llmaw:new", "migrate_from": ["llmaw:old"]}]
    renames, conflicts = base.plan_label_migrations(declared, {"llmaw:old", "llmaw:new"})
    assert renames == []
    assert conflicts == [("llmaw:old", "llmaw:new")]


def test_plan_migrations_accepts_string_migrate_from():
    declared = [{"name": "llmaw:new", "migrate_from": "llmaw:old"}]
    renames, _ = base.plan_label_migrations(declared, {"llmaw:old"})
    assert renames == [("llmaw:old", "llmaw:new")]


def test_plan_migrations_second_old_conflicts_after_target_created():
    # Two predecessors merging into one target: only the first can rename.
    declared = [{"name": "llmaw:new", "migrate_from": ["llmaw:old1", "llmaw:old2"]}]
    renames, conflicts = base.plan_label_migrations(declared, {"llmaw:old1", "llmaw:old2"})
    assert renames == [("llmaw:old1", "llmaw:new")]
    assert conflicts == [("llmaw:old2", "llmaw:new")]


def test_plan_migrations_no_migrate_from_is_noop():
    declared = [{"name": "llmaw:plain", "description": "x", "color": "FFFFFF"}]
    renames, conflicts = base.plan_label_migrations(declared, {"llmaw:plain"})
    assert renames == []
    assert conflicts == []


def test_normalize_migrate_from_rejects_non_string_entry():
    with pytest.raises(ConfigError):
        base.normalize_migrate_from([1, 2])


def test_normalize_migrate_from_rejects_non_list():
    with pytest.raises(ConfigError):
        base.normalize_migrate_from(42)


def test_github_rename_label_calls_gh_with_name_flag(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return None

    monkeypatch.setattr(github.subprocess, "run", fake_run)

    github.GithubCliClient.rename_label("llmaw:old", "llmaw:new")

    assert captured["cmd"] == [
        "gh",
        "label",
        "edit",
        "llmaw:old",
        "--name",
        "llmaw:new",
    ]


def _write_subject(state_dir, name: str, labels: list[str]) -> None:
    path = state_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        local.yaml.safe_dump({"labels": labels, "state": "open", "comments": []}),
    )


def test_local_sync_labels_migrates_subject_files(tmp_path):
    client = local.LocalYamlClient(tmp_path)
    _write_subject(tmp_path, "issue-1.yml", ["llmaw:old", "other"])

    defs = [
        {"name": "llmaw:new", "description": "d", "color": "FBCA04", "migrate_from": ["llmaw:old"]},
        {"name": "other", "description": "d", "color": "FBCA04"},
    ]
    client.sync_labels(defs)

    assert client.get_labels(local.SubjectRef("issue", "1")) == ["llmaw:new", "other"]
    catalog = local.yaml.safe_load((tmp_path / local.LABELS_FILE).read_text())
    assert [item["name"] for item in catalog["labels"]] == ["llmaw:new", "other"]
    assert all("migrate_from" not in item for item in catalog["labels"])


def test_local_sync_labels_keeps_conflicting_names(tmp_path):
    client = local.LocalYamlClient(tmp_path)
    _write_subject(tmp_path, "issue-1.yml", ["llmaw:old"])
    _write_subject(tmp_path, "issue-2.yml", ["llmaw:new"])

    defs = [
        {"name": "llmaw:new", "description": "d", "color": "FBCA04", "migrate_from": ["llmaw:old"]},
    ]
    client.sync_labels(defs)

    assert client.get_labels(local.SubjectRef("issue", "1")) == ["llmaw:old"]
    assert client.get_labels(local.SubjectRef("issue", "2")) == ["llmaw:new"]
