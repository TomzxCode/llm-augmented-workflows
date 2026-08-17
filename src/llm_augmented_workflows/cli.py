"""Command-line interface for the LLM-Augmented Workflows engine.

Most subcommands read their inputs from environment variables (the contract the
GitHub Actions workflow sets). ``trigger`` and ``run-rule``'s flags are the
local-mode entry points, replacing the GitHub webhook loop. Installed as the
``llmaw`` console script.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from . import apply_outcome, engine, route, run_rule, run_steps, sync_labels
from .trackers import load_tracker
from .trackers.base import SubjectRef
from .trackers.local import CliEventSource

log = logging.getLogger("cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmaw",
        description="LLM-Augmented Workflows engine.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("route", help="match an event to flows.yml rules")
    run_steps_parser = sub.add_parser(
        "run-steps", help="run the deterministic steps of a matched rule"
    )
    run_steps_parser.add_argument("phase", nargs="?", default="pre", choices=["pre", "post"])
    run_rule_parser = sub.add_parser(
        "run-rule",
        help="execute matched rules end to end (pre -> agent -> post -> on_outcome)",
    )
    run_rule_parser.add_argument("--rule-id", help="force-run a single rule by id (dry run)")
    run_rule_parser.add_argument("--issue", help="subject issue number")
    run_rule_parser.add_argument("--pr", help="subject pull request number")
    sub.add_parser("apply-outcome", help="apply a rule's on_outcome action from $OUTCOME_YAML")
    sub.add_parser("sync-labels", help="create/update labels declared in flows.yml")

    trigger_parser = sub.add_parser(
        "trigger", help="emit an event and run the matched rules (local mode driver)"
    )
    trigger_parser.add_argument("event", help="event name: issues | pull_request | issue_comment")
    trigger_parser.add_argument(
        "action", nargs="?", default=None, help="event action: opened | labeled | closed | created"
    )
    subject = trigger_parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--issue", help="subject issue number")
    subject.add_argument("--pr", help="subject pull request number")
    trigger_parser.add_argument("--label", help="label name (labeled events)")
    trigger_parser.add_argument("--title", help="subject title")
    trigger_parser.add_argument("--body", help="subject body text")
    trigger_parser.add_argument("--branch", help="head branch (pull_request events)")
    trigger_parser.add_argument(
        "--merged", action="store_true", help="mark the pull request merged"
    )
    trigger_parser.add_argument("--comment-author", help="comment author (comment events)")
    trigger_parser.add_argument("--comment-body", help="comment body (comment events)")
    trigger_parser.add_argument(
        "--execution", choices=list(engine.EXECUTION_MODES), help="force execution mode"
    )
    return parser


def _flows_and_rules() -> tuple[dict, list[engine.Rule]] | None:
    flows_path = os.environ.get("FLOWS_FILE", ".github/llmaw/flows.yml")
    try:
        flows_raw = engine.load_flows(flows_path)
        all_rules = engine.flatten_rules(
            flows_raw, os.environ.get("MODEL", ""), os.environ.get("AGENTS_REPOSITORY", "")
        )
    except engine.ConfigError as exc:
        log.error("invalid flows config: %s", exc)
        return None
    return flows_raw, all_rules


def _mk_workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="llmaw-"))


def _set_subject_env(ref: SubjectRef, args: argparse.Namespace, comment: dict | None) -> None:
    if ref.kind == "issue":
        os.environ["ISSUE_NUMBER"] = ref.id
        if args.title is not None:
            os.environ["ISSUE_TITLE"] = args.title
        if args.body is not None:
            os.environ["ISSUE_BODY"] = args.body
    else:
        os.environ["PR_NUMBER"] = ref.id
        if args.title is not None:
            os.environ["PR_TITLE"] = args.title
        if args.body is not None:
            os.environ["PR_BODY"] = args.body
        if args.branch is not None:
            os.environ["PR_BRANCH"] = args.branch
        os.environ["PR_MERGED"] = "true" if args.merged else "false"
    if args.label is not None:
        os.environ["LABEL"] = args.label
    if comment:
        os.environ["COMMENT_AUTHOR"] = comment.get("author") or ""
        os.environ["COMMENT_BODY"] = comment.get("body") or ""
        os.environ["COMMENT_TYPE"] = comment.get("type") or "general"


def _cmd_trigger(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ref = SubjectRef("issue", args.issue) if args.issue else SubjectRef("pull_request", args.pr)

    comment = None
    if args.comment_body is not None or args.comment_author is not None:
        comment = {
            "author": args.comment_author,
            "body": args.comment_body or "",
            "type": "inline" if args.event == "pull_request_review_comment" else "general",
        }
    event = CliEventSource(
        args.event,
        args.action,
        ref,
        label=args.label,
        merged=args.merged,
        branch=args.branch,
        title=args.title,
        body=args.body,
        comment=comment,
    ).event()

    loaded = _flows_and_rules()
    if loaded is None:
        return 1
    flows_raw, all_rules = loaded
    try:
        client = load_tracker(flows_raw)
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    _set_subject_env(ref, args, comment)
    # A `labeled` event means the label is present; assert it into local state
    # before rules run (GitHub state is authoritative there, so skip it).
    if args.action == "labeled" and args.label and client.name == "local":
        client.add_labels(ref, [args.label])
    os.environ["ISSUE_LABELS"] = ",".join(client.get_labels(ref))

    rules = [r for r in all_rules if engine.matches(r.when, event)]
    matrix = [engine.rule_to_matrix(r) for r in rules]
    override = (args.execution or os.environ.get("EXECUTION") or "").strip().lower()
    execution = engine.resolve_dispatch_execution(flows_raw, rules, override)

    log.info(
        "trigger %s.%s subject=%s#%s execution=%s matched=%s",
        args.event,
        args.action or "-",
        client.name,
        ref.id,
        execution,
        [m["id"] for m in matrix] or "none",
    )
    if not matrix:
        return 0

    workdir = _mk_workdir()
    os.environ["MATCHED_FILE"] = str(workdir / "matched.json")
    Path(os.environ["MATCHED_FILE"]).write_text(json.dumps(matrix))
    os.environ.setdefault("OUTCOME_YAML", str(workdir / "outcome.yaml"))
    os.environ["EXECUTION"] = execution
    return run_rule.main()


def _cmd_run_rule(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.issue and args.pr:
        log.error("--issue and --pr are mutually exclusive")
        return 2
    if args.issue:
        os.environ["ISSUE_NUMBER"] = args.issue
        os.environ.pop("PR_NUMBER", None)
    if args.pr:
        os.environ["PR_NUMBER"] = args.pr
        os.environ.pop("ISSUE_NUMBER", None)

    if args.rule_id:
        loaded = _flows_and_rules()
        if loaded is None:
            return 1
        _, all_rules = loaded
        rule = next((r for r in all_rules if r.id == args.rule_id), None)
        if rule is None:
            log.error("no rule with id '%s'", args.rule_id)
            return 1
        workdir = _mk_workdir()
        matched = workdir / "matched.json"
        matched.write_text(json.dumps([engine.rule_to_matrix(rule)]))
        os.environ["MATCHED_FILE"] = str(matched)
        os.environ.pop("MATCHED_RULE", None)
        os.environ.setdefault("OUTCOME_YAML", str(workdir / "outcome.yaml"))
        log.info("dry run: forced rule %s", args.rule_id)
    return run_rule.main()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "trigger":
        return _cmd_trigger(args)
    if args.command == "run-rule":
        return _cmd_run_rule(args)
    if args.command == "run-steps":
        return run_steps.main(args.phase)
    commands = {
        "route": route.main,
        "apply-outcome": apply_outcome.main,
        "sync-labels": sync_labels.main,
    }
    return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())
