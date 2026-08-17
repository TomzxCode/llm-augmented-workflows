"""GitHub adapter: tracker mutations via the ``gh`` CLI (``GH_TOKEN``) and
event ingestion from the GitHub Actions runtime (``GITHUB_EVENT_*``).

This is the code that used to live inline in ``run_steps.py`` /
``apply_outcome.py`` / ``sync_labels.py``, extracted behind the
:class:`~llm_augmented_workflows.trackers.base.TrackerClient` port.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from .base import CanonicalEvent, SubjectRef, parse_linked_issue

log = logging.getLogger(__name__)


def _gh(args: list[str], *, capture: bool = False) -> str:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=capture,
        text=True,
        check=True,
    )
    return proc.stdout if capture else ""


def _run_url() -> str | None:
    """Actions run URL built from the ``GITHUB_*`` runtime env vars, or ``None``."""
    server = os.environ.get("GITHUB_SERVER_URL")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


def _with_run_link(body: str) -> str:
    """Append a workflow-run footer to a comment body when running in Actions."""
    url = _run_url()
    if not url:
        return body
    return f"{body}\n\n---\n[Workflow run]({url})"


class GithubCliClient:
    """:class:`TrackerClient` backed by the ``gh`` CLI."""

    name = "github"

    @staticmethod
    def _sub(ref: SubjectRef) -> str:
        return "pr" if ref.kind == "pull_request" else "issue"

    def get_labels(self, ref: SubjectRef) -> list[str]:
        out = _gh(
            [self._sub(ref), "view", ref.id, "--json", "labels", "-q", ".labels[].name"],
            capture=True,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]

    def add_labels(self, ref: SubjectRef, labels: list[str]) -> None:
        _gh([self._sub(ref), "edit", ref.id, "--add-label", ",".join(labels)])

    def remove_labels(self, ref: SubjectRef, labels: list[str]) -> None:
        _gh([self._sub(ref), "edit", ref.id, "--remove-label", ",".join(labels)])

    def comment(self, ref: SubjectRef, body: str) -> None:
        _gh([self._sub(ref), "comment", ref.id, "--body", _with_run_link(body)])

    def close(self, ref: SubjectRef, comment: str | None) -> None:
        args = [self._sub(ref), "close", ref.id]
        if comment:
            args += ["--comment", _with_run_link(comment)]
        _gh(args)

    def find_linked_subject(self, ref: SubjectRef) -> SubjectRef | None:
        """Find an issue referenced in the PR title/body env of this dispatch."""
        text = f"{os.environ.get('PR_TITLE', '')} {os.environ.get('PR_BODY', '')}"
        number = parse_linked_issue(text)
        return SubjectRef("issue", number) if number else None

    def sync_labels(self, defs: list[dict]) -> None:
        for label in defs:
            self._sync_label(
                name=label["name"],
                description=label.get("description", ""),
                color=label.get("color", ""),
            )

    @staticmethod
    def _sync_label(name: str, description: str, color: str) -> None:
        """Create a label, or update it if it already exists."""
        create = subprocess.run(
            ["gh", "label", "create", name, "--description", description, "--color", color],
            capture_output=True,
            text=True,
        )
        if create.returncode == 0:
            log.info("created label %s", name)
            return
        subprocess.run(
            ["gh", "label", "edit", name, "--description", description, "--color", color],
            check=True,
        )
        log.info("updated label %s", name)


def from_github_payload(event_name: str, payload: dict) -> CanonicalEvent:
    """Project a GitHub webhook/Actions payload into a :class:`CanonicalEvent`."""
    issue = payload.get("issue") or {}
    pr = payload.get("pull_request") or {}
    subject: SubjectRef | None = None
    title = None
    body = None
    if issue.get("number") is not None:
        subject = SubjectRef("issue", str(issue["number"]))
        title, body = issue.get("title"), issue.get("body")
    elif pr.get("number") is not None:
        subject = SubjectRef("pull_request", str(pr["number"]))
        title, body = pr.get("title"), pr.get("body")

    comment_payload = payload.get("comment") or {}
    comment = None
    if comment_payload:
        comment = {
            "author": (comment_payload.get("user") or {}).get("login"),
            "body": comment_payload.get("body"),
            "type": "inline" if event_name == "pull_request_review_comment" else "general",
        }

    return CanonicalEvent(
        event=event_name,
        action=payload.get("action"),
        subject=subject,
        label=(payload.get("label") or {}).get("name"),
        merged=pr.get("merged"),
        branch=(pr.get("head") or {}).get("ref"),
        title=title,
        body=body,
        comment=comment,
        raw=payload,
    )


class GithubActionsEventSource:
    """:class:`EventSource` reading the GitHub Actions runtime environment."""

    @staticmethod
    def event_name() -> str:
        return os.environ.get("GITHUB_EVENT_NAME", "")

    def event(self) -> CanonicalEvent | None:
        name = self.event_name()
        path = os.environ.get("GITHUB_EVENT_PATH")
        if not name or not path or not Path(path).exists():
            return None
        payload = json.loads(Path(path).read_text())
        if not isinstance(payload, dict):
            return None
        return from_github_payload(name, payload)
