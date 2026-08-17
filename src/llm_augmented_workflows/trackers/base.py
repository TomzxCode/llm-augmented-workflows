"""Tracker-agnostic ports shared by the engine and its adapters.

The engine core (``engine.py``) is pure: it loads config, matches canonical
events to rules, and normalizes steps. Everything that reads or mutates issue
tracker state goes through the :class:`TrackerClient` protocol, and everything
that produces an event goes through the :class:`EventSource` protocol.
``trackers/github.py`` (``gh`` CLI, GitHub Actions runtime) and
``trackers/local.py`` (per-subject YAML state files, CLI flags) provide the
adapters used by the ``tracker:`` config in ``flows.yml``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

_LINKED_KEYWORD_RE = re.compile(
    r"(?:closes|fixes|resolves|plan for issue)[^#\n]*#(\d+)", re.IGNORECASE
)
_ANY_REF_RE = re.compile(r"#(\d+)")


@dataclass(frozen=True)
class SubjectRef:
    """Tracker-agnostic handle for the subject of an event or mutation."""

    kind: str  # "issue" | "pull_request"
    id: str


def parse_linked_issue(text: str) -> str | None:
    """Extract a referenced issue id from ``text`` (PR title/body).

    Prefers an explicit keyword reference (``closes #42``, ``plan for issue
    #42``), then falls back to any ``#N``.
    """
    m = _LINKED_KEYWORD_RE.search(text)
    if m:
        return m.group(1)
    m = _ANY_REF_RE.search(text)
    return m.group(1) if m else None


@dataclass(frozen=True)
class CanonicalEvent:
    """Normalized event; the only thing the matcher looks at.

    Field names keep the GitHub vocabulary (``event: issues``, ``action:
    labeled``) as the canonical terms, so ``flows.yml`` ``when`` blocks are
    tracker-independent. ``raw`` carries the original payload for adapters
    that need exotic fields.
    """

    event: str
    action: str | None = None
    subject: SubjectRef | None = None
    label: str | None = None
    merged: bool | None = None
    branch: str | None = None
    title: str | None = None
    body: str | None = None
    comment: dict | None = None  # {author, body, type: general|inline}
    raw: dict = field(default_factory=dict)


class TrackerClient(Protocol):
    """Every tracker read/mutation the engine performs.

    Labels are the only state the engine ever reads back (label diff,
    continuous chaining). ``comment``/``close`` are writes the engine does not
    read back. The agent env contract (``ISSUE_TITLE``, ``PR_BODY``, ...) is
    derived from the event by the event source, never served by a client.
    """

    name: str

    def get_labels(self, ref: SubjectRef) -> list[str]: ...
    def add_labels(self, ref: SubjectRef, labels: list[str]) -> None: ...
    def remove_labels(self, ref: SubjectRef, labels: list[str]) -> None: ...
    def comment(self, ref: SubjectRef, body: str) -> None: ...
    def close(self, ref: SubjectRef, comment: str | None) -> None: ...
    def find_linked_subject(self, ref: SubjectRef) -> SubjectRef | None: ...
    def sync_labels(self, defs: list[dict]) -> None: ...


class EventSource(Protocol):
    """Produces the canonical event for one dispatch."""

    def event(self) -> CanonicalEvent | None: ...
