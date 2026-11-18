"""Unit tests for ben.kb.match (S1) — does not touch default search()."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ben.kb import KnowledgeBase
from ben.kb import match as M


ROOT = Path(__file__).resolve().parents[1]
KB_ROOT = ROOT / "ben" / "kb"
TAX = json.loads((KB_ROOT / "taxonomy.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def entries() -> dict[str, dict]:
    kb = KnowledgeBase(KB_ROOT)
    return {e["id"]: e for e in kb.list_entries()}


def test_surface_tokens_non_overlapping():
    assert M.surface_tokens("布尔盲注") == ["布尔", "盲注"]
    assert "尔盲" not in M.surface_tokens("布尔盲注")


def test_提权_on_kb002_is_miss(entries):
    r = M.check_scope("提权", [entries["kb002"]], taxonomy=TAX)
    assert r.state == M.MISS
    assert r.exit_code == 1


def test_提权_scope_with_kb012_hits(entries):
    r = M.check_scope(
        "提权", [entries["kb001"], entries["kb012"]], taxonomy=TAX,
    )
    assert r.state == M.HIT
    assert r.exit_code == 0
    assert any(v.entry_id == "kb012" and v.state == M.HIT for v in r.verdicts)


def test_sql_注入_hits_kb002(entries):
    r = M.check_scope(
        "sql 注入", [entries["kb001"], entries["kb002"]], taxonomy=TAX,
    )
    assert r.state == M.HIT
    assert any(v.entry_id == "kb002" and v.state == M.HIT for v in r.verdicts)


def test_布尔盲注_weak_without_qualifier_in_entry(entries):
    r = M.check_scope(
        "布尔盲注", [entries["kb001"], entries["kb002"]], taxonomy=TAX,
    )
    assert r.state == M.WEAK
    assert r.exit_code == 1
    assert r.split.group == "布尔"


def test_detail_scatter_does_not_make_二次注入_hit(entries):
    """Without content for 二次注入, scope kb001+kb002 must not HIT via detail chars."""
    r = M.check_scope(
        "二次注入", [entries["kb001"], entries["kb002"]], taxonomy=TAX,
    )
    assert r.state != M.HIT


def test_default_search_untouched_smoke():
    """S1 must not change KnowledgeBase.search ranking API shape."""
    kb = KnowledgeBase(KB_ROOT)
    hits = kb.search("sql 注入", limit=3)
    assert hits and hits[0]["id"] == "kb002"
    assert hits[0]["score"] == 1.0
