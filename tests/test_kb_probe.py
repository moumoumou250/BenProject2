"""Offline gates for ben probe (S4) — no live target required."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BEN = ROOT / "bin" / "ben"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BEN), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_probe_unknown_vuln_is_2():
    p = _run("probe", "tomcat-cve-2017-12615", "内存马")
    assert p.returncode == 2
    assert "not in taxonomy" in p.stderr


def test_probe_swapped_args_is_2():
    p = _run("probe", "file-write", "tomcat-cve-2017-12615")
    assert p.returncode == 2


def test_probe_budget_zero_is_3():
    p = _run(
        "probe", "tomcat-cve-2017-12615", "file-write",
        "--allow-destructive", "--max-requests", "0",
    )
    assert p.returncode == 3
    assert "BUDGET" in p.stdout


def test_probe_without_destructive_is_1():
    p = _run("probe", "tomcat-cve-2017-12615", "file-write")
    assert p.returncode == 1
    assert "allow-destructive" in p.stdout


def test_kb003_has_validation_signal():
    entry = json.loads((ROOT / "ben/kb/entries/kb003.json").read_text(encoding="utf-8"))
    assert entry["validation"]["signal"].strip()


def test_host_allowed_helpers():
    from ben.commands.probe_cmds import host_allowed
    assert host_allowed("127.0.0.1", authorized=False)
    assert host_allowed("10.0.0.5", authorized=False)
    assert not host_allowed("8.8.8.8", authorized=False)
    assert host_allowed("8.8.8.8", authorized=True)
