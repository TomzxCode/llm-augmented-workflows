"""Unit tests for run_steps.run_shell (argv + tooling-root resolution)."""

from __future__ import annotations

from llm_augmented_workflows import run_steps


def test_run_shell_string_form_no_args(monkeypatch):
    monkeypatch.delenv("LLMAW_TOOLING_ROOT", raising=False)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return None

    monkeypatch.setattr(run_steps.subprocess, "run", fake_run)

    run_steps.run_shell({"shell": "s.sh"})

    assert captured["cmd"] == ["bash", "s.sh"]


def test_run_shell_dict_form_passes_args_as_argv(monkeypatch):
    monkeypatch.delenv("LLMAW_TOOLING_ROOT", raising=False)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return None

    monkeypatch.setattr(run_steps.subprocess, "run", fake_run)

    run_steps.run_shell({"shell": {"run": "s.sh", "args": ["draft requirements"]}})

    assert captured["cmd"] == ["bash", "s.sh", "draft requirements"]


def test_run_shell_resolves_relative_script_via_tooling_root(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return None

    monkeypatch.setattr(run_steps.subprocess, "run", fake_run)

    tooling = tmp_path / "tooling"
    script_rel = ".github/llmaw/scripts/commit-sdlc.sh"
    script_abs = tooling / script_rel
    script_abs.parent.mkdir(parents=True)
    script_abs.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setenv("LLMAW_TOOLING_ROOT", str(tooling))

    # run_shell receives the normalized dict form (list form is normalized away
    # at matrix-build time by normalize_shell_step)
    run_steps.run_shell({"shell": {"run": script_rel, "args": ["draft x"]}})

    assert captured["cmd"][0] == "bash"
    assert captured["cmd"][1] == str(script_abs)
    assert captured["cmd"][2:] == ["draft x"]


def test_run_shell_falls_back_when_tooling_root_unset(monkeypatch):
    monkeypatch.delenv("LLMAW_TOOLING_ROOT", raising=False)
    captured = {}
    monkeypatch.setattr(
        run_steps.subprocess, "run", lambda cmd, **k: captured.__setitem__("cmd", cmd) or None
    )

    run_steps.run_shell({"shell": "s.sh"})

    assert captured["cmd"] == ["bash", "s.sh"]


def test_run_shell_falls_back_when_snapshot_lacks_file(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        run_steps.subprocess, "run", lambda cmd, **k: captured.__setitem__("cmd", cmd) or None
    )
    # tooling root set but the script is not present in the snapshot
    monkeypatch.setenv("LLMAW_TOOLING_ROOT", str(tmp_path))

    run_steps.run_shell({"shell": "s.sh"})

    assert captured["cmd"] == ["bash", "s.sh"]
