"""CLI acceptance for ben kb check / diagnose (S2 §9)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEN = ROOT / "bin" / "ben"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BEN), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_check_sql_inject_hit():
    p = _run("kb", "check", "sql 注入", "--only", "kb001,kb002")
    assert p.returncode == 0
    assert "verdict: HIT" in p.stdout


def test_check_布尔盲注_weak():
    p = _run("kb", "check", "布尔盲注", "--only", "kb001,kb002")
    assert p.returncode == 1
    assert "verdict: WEAK" in p.stdout


def test_check_提权_on_kb002_miss():
    p = _run("kb", "check", "提权", "--only", "kb002")
    assert p.returncode == 1
    assert "verdict: MISS" in p.stdout


def test_check_文件上传_on_kb002_miss():
    p = _run("kb", "check", "文件上传", "--only", "kb002")
    assert p.returncode == 1


def test_check_提权_with_kb012_hit():
    p = _run("kb", "check", "提权", "--only", "kb001,kb012")
    assert p.returncode == 0
    assert "verdict: HIT" in p.stdout


def test_diagnose_布尔盲注_default_is_inconclusive():
    """Group aliases alone stay WEAK on kb002 (no distinctive 布尔/盲注)."""
    p = _run("kb", "diagnose", "布尔盲注", "--only", "kb001,kb002")
    assert p.returncode == 3
    assert "无法归因" in p.stdout


def test_diagnose_布尔盲注_naming_gap_with_explicit_variants():
    p = _run(
        "kb", "diagnose", "布尔盲注", "--only", "kb001,kb002",
        "--variants", "布尔盲注,sql 注入",
    )
    assert p.returncode == 0
    assert "叫法缺口" in p.stdout


def test_diagnose_二次注入_inconclusive_or_content():
    """Subtype aliases do not HIT on general sqli entry → no HIT in variant set."""
    p = _run("kb", "diagnose", "二次注入", "--only", "kb001,kb002")
    assert p.returncode in (1, 3)
    assert ("内容缺口" in p.stdout) or ("无法归因" in p.stdout)


def test_diagnose_内存马_needs_variants():
    p = _run("kb", "diagnose", "内存马", "--only", "kb001,kb002")
    assert p.returncode == 2


def test_check_unknown_id_is_2():
    p = _run("kb", "check", "x", "--only", "kb999")
    assert p.returncode == 2
    assert "unknown kb id" in p.stderr


def test_check_empty_only_is_2():
    p = _run("kb", "check", "x", "--only", "")
    assert p.returncode == 2


def test_search_sql_baseline_unchanged():
    p = _run("kb", "search", "sql 注入", "--limit", "3")
    assert p.returncode == 0
    assert p.stdout.splitlines()[0].startswith("kb002\tscore=1.0")
