"""Unit tests for run_steps.run_shell (argv handling)."""

from __future__ import annotations

from llm_augmented_workflows import run_steps


def test_run_shell_string_form_no_args(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return None

    monkeypatch.setattr(run_steps.subprocess, "run", fake_run)

    run_steps.run_shell({"shell": "s.sh"})

    assert captured["cmd"] == ["bash", "s.sh"]


def test_run_shell_dict_form_passes_args_as_argv(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return None

    monkeypatch.setattr(run_steps.subprocess, "run", fake_run)

    run_steps.run_shell({"shell": {"run": "s.sh", "args": ["draft requirements"]}})

    assert captured["cmd"] == ["bash", "s.sh", "draft requirements"]
