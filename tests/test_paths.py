"""The runtime-output rule: one root, and no path arithmetic at call sites.

These tests pin the *shape* of the layout, not an absolute path — the point of
`ben/core/paths.py` is that changing `BEN_RUNTIME_DIR` moves everything at once.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ben.core import paths
from ben.runtime.agents import fleet_registry_root
from ben.runtime.console import _save_sessions, console_root


def test_default_name_is_runs(monkeypatch):
    monkeypatch.delenv("BEN_RUNTIME_DIR", raising=False)
    assert paths.runtime_name() == paths.DEFAULT_RUNTIME_DIR


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("BEN_RUNTIME_DIR", "out")
    assert paths.runtime_name() == "out"
    assert paths.runtime_root("/proj") == Path("/proj/out")


@pytest.mark.parametrize("bad", ["", "  ", "/", "../x", "a/b", "."])
def test_bad_override_falls_back_instead_of_escaping(monkeypatch, bad):
    """A value with a slash (or `..`) could write outside the base dir."""
    monkeypatch.setenv("BEN_RUNTIME_DIR", bad)
    assert paths.runtime_name() == paths.DEFAULT_RUNTIME_DIR


def test_output_dir_moves_off_the_base_dir(tmp_path):
    assert paths.output_dir(tmp_path) == tmp_path / paths.DEFAULT_RUNTIME_DIR


def test_output_dir_does_not_nest(tmp_path):
    """A store already at runs/<name>/.ben must not get runs/<name>/runs/."""
    inside = tmp_path / paths.DEFAULT_RUNTIME_DIR / "juice"
    assert paths.output_dir(inside) == inside
    assert paths.snapshot_file(inside) == inside / "ben-graph.html"


def test_registry_and_logs_share_the_root(tmp_path):
    assert paths.registry_root(tmp_path) == paths.runtime_root(tmp_path)
    assert paths.logs_dir(tmp_path) == paths.runtime_root(tmp_path) / "logs"
    assert not paths.logs_dir(tmp_path).exists(), "readers must not mkdir"


def test_ensure_output_dir_creates(tmp_path):
    out = paths.ensure_output_dir(tmp_path)
    assert out.is_dir()


def test_console_sessions_live_under_the_runtime_root(tmp_path):
    """A PTY socket dir next to the source tree is the bug this rule kills."""
    root = console_root(tmp_path)
    assert root == tmp_path / paths.DEFAULT_RUNTIME_DIR / "console"


def test_console_root_does_not_create_anything_by_being_asked(tmp_path):
    """`ben peers` lists consoles; listing must not make a directory."""
    assert not console_root(tmp_path).exists()


def test_writing_a_session_creates_its_directory(tmp_path):
    _save_sessions(tmp_path, {"version": 1, "sessions": {}})
    assert (tmp_path / paths.DEFAULT_RUNTIME_DIR / "console" / "sessions.json").is_file()


def test_fleet_registry_defaults_to_the_runtime_root(tmp_path):
    assert fleet_registry_root(tmp_path) == tmp_path.resolve() / paths.DEFAULT_RUNTIME_DIR


def test_fleet_registry_honours_an_explicit_root_from_fleet_json(tmp_path):
    """fleet.json may name a different root; only the *default* is centralized."""
    assert fleet_registry_root(tmp_path, "arena") == tmp_path.resolve() / "arena"


def test_nothing_in_the_package_hardcodes_the_name():
    """Belt and braces: arch_check enforces this, but a unit test fails faster."""
    root = Path(paths.__file__).resolve().parent.parent
    offenders = []
    for p in root.rglob("*.py"):
        if p.name == "paths.py" or "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        if f'"{paths.DEFAULT_RUNTIME_DIR}"' in text or f"'{paths.DEFAULT_RUNTIME_DIR}'" in text:
            offenders.append(str(p.relative_to(root)))
    assert offenders == []
