"""Local, trackerless adapter: state lives in per-subject YAML files.

The engine reads exactly one thing from tracker state (labels), so a subject
file is mostly a label list plus write-only record. Everything else (title,
body, branch, merged) is event-time data provided by ``llmaw trigger`` flags
and never persisted. Files are named ``<kind>-<id>.yml`` with the kind's
underscore as a hyphen (``issue-1.yml``, ``pull-request-2.yml``).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .base import (
    CanonicalEvent,
    SubjectRef,
    log_migration_conflicts,
    parse_linked_issue,
    plan_label_migrations,
)

log = logging.getLogger(__name__)

LABELS_FILE = "labels.yml"


class LocalYamlClient:
    """:class:`TrackerClient` backed by per-subject YAML files in a state dir."""

    name = "local"

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)

    def _path(self, ref: SubjectRef) -> Path:
        return self.state_dir / f"{ref.kind.replace('_', '-')}-{ref.id}.yml"

    def _read(self, ref: SubjectRef) -> dict:
        path = self._path(ref)
        if not path.exists():
            return {"labels": [], "state": "open", "comments": []}
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("labels", [])
        data.setdefault("state", "open")
        data.setdefault("comments", [])
        return data

    def _write(self, ref: SubjectRef, data: dict) -> None:
        path = self._path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False))
        os.replace(tmp, path)

    def get_labels(self, ref: SubjectRef) -> list[str]:
        return list(self._read(ref)["labels"])

    def add_labels(self, ref: SubjectRef, labels: list[str]) -> None:
        data = self._read(ref)
        current = data["labels"]
        for label in labels:
            if label not in current:
                current.append(label)
        data["labels"] = current
        self._write(ref, data)

    def remove_labels(self, ref: SubjectRef, labels: list[str]) -> None:
        data = self._read(ref)
        data["labels"] = [item for item in data["labels"] if item not in set(labels)]
        self._write(ref, data)

    def comment(self, ref: SubjectRef, body: str) -> None:
        data = self._read(ref)
        data["comments"].append({"body": body, "at": datetime.now(UTC).isoformat()})
        self._write(ref, data)

    def close(self, ref: SubjectRef, comment: str | None) -> None:
        data = self._read(ref)
        if comment:
            data["comments"].append({"body": comment, "at": datetime.now(UTC).isoformat()})
        data["state"] = "closed"
        self._write(ref, data)

    def find_linked_subject(self, ref: SubjectRef) -> SubjectRef | None:
        """Resolve the issue a pseudo-MR points at.

        An explicit ``linked: issue-1`` pointer in the MR's file wins; else the
        same ``#N`` regex runs over the event's ``PR_TITLE``/``PR_BODY`` env.
        Returns ``None`` when the target has no state file.
        """
        linked = self._read(ref).get("linked")
        if linked:
            kind, _, sid = str(linked).rpartition("-")
            if kind and sid:
                target = SubjectRef(kind, sid)
                if self._path(target).exists():
                    return target
                return None
        text = f"{os.environ.get('PR_TITLE', '')} {os.environ.get('PR_BODY', '')}"
        number = parse_linked_issue(text)
        if number:
            target = SubjectRef("issue", number)
            if self._path(target).exists():
                return target
        return None

    def sync_labels(self, defs: list[dict]) -> None:
        """Migrate declared predecessors, then write the label catalog.

        Migration here rewrites the label name in every subject file (and the
        catalog) that still carries it, matching the rename semantics of the
        GitHub tracker.
        """
        existing = self._all_label_names()
        renames, conflicts = plan_label_migrations(defs, existing)
        rename_map = dict(renames)
        if rename_map:
            for path in sorted(self.state_dir.glob("*.yml")):
                if path.name == LABELS_FILE:
                    continue
                data = yaml.safe_load(path.read_text()) or {}
                if not isinstance(data, dict):
                    continue
                labels = data.get("labels") or []
                if any(item in rename_map for item in labels):
                    data["labels"] = [rename_map.get(item, item) for item in labels]
                    tmp = path.with_name(path.name + ".tmp")
                    tmp.write_text(yaml.safe_dump(data, sort_keys=False))
                    os.replace(tmp, path)
            for old, new in renames:
                log.info("renamed label %s -> %s", old, new)
        log_migration_conflicts(conflicts, log)

        catalog = [{k: v for k, v in label.items() if k != "migrate_from"} for label in defs]
        path = self.state_dir / LABELS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(yaml.safe_dump({"labels": catalog}, sort_keys=False))
        os.replace(tmp, path)
        log.info("wrote label catalog %s (%d labels)", path, len(defs))

    def _all_label_names(self) -> set[str]:
        """Every label name in play: catalog entries plus subject-file labels."""
        names: set[str] = set()
        catalog = self.state_dir / LABELS_FILE
        if catalog.exists():
            data = yaml.safe_load(catalog.read_text()) or {}
            names.update(
                item["name"] for item in (data.get("labels") or []) if isinstance(item, dict)
            )
        for path in self.state_dir.glob("*.yml"):
            if path.name == LABELS_FILE:
                continue
            data = yaml.safe_load(path.read_text()) or {}
            if isinstance(data, dict):
                names.update(data.get("labels") or [])
        return names


class CliEventSource:
    """:class:`EventSource` built from ``llmaw trigger`` CLI flags."""

    def __init__(
        self,
        event_name: str,
        action: str | None,
        ref: SubjectRef,
        *,
        label: str | None = None,
        merged: bool = False,
        branch: str | None = None,
        title: str | None = None,
        body: str | None = None,
        comment: dict | None = None,
    ):
        self._event_name = event_name
        self._action = action
        self._ref = ref
        self._label = label
        self._merged = merged
        self._branch = branch
        self._title = title
        self._body = body
        self._comment = comment

    def event(self) -> CanonicalEvent | None:
        return CanonicalEvent(
            event=self._event_name,
            action=self._action,
            subject=self._ref,
            label=self._label,
            merged=True if self._merged else None,
            branch=self._branch,
            title=self._title,
            body=self._body,
            comment=self._comment,
        )
