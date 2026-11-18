"""KB reachability matcher for `ben kb check` / `diagnose`.

Parallel to `KnowledgeBase.search()` — does NOT change default search/tokenize.
CJK uses non-overlapping digrams; taxonomy aliases win via longest match first.
`detail` is excluded from the match surface (confirmed plan §附录 A).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

DEFAULT_THRESHOLD = 0.6
STOPWORDS = frozenset("的了和与在是有不无把被为".split())
# Too generic to prove a qualifier (e.g. group alias "blind sql" must not
# count as qualifier-hit just because the entry mentions SQL).
_QUALIFIER_NOISE = frozenset({"sql", "web", "http", "cve", "漏洞", "注入", "injection", "sqli"})
_WORD_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+", re.IGNORECASE)
HIT, WEAK, MISS = "HIT", "WEAK", "MISS"
_FIELD_WEIGHT = {
    "title": 3,
    "description": 2,
    "tags": 2,
    "validation": 2,
}


@dataclass
class SplitQuery:
    core: list[str]
    qualifier: list[str]
    note: str = ""
    subject: str | None = None
    group: str | None = None


@dataclass
class EntryVerdict:
    entry_id: str
    state: str
    core_coverage: float
    qualifier_hit: bool
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    state: str
    exit_code: int
    query: str
    split: SplitQuery
    verdicts: list[EntryVerdict]
    excluded: int = 0


def load_taxonomy(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"taxonomy root must be object: {path}")
    if "subjects" in data and not isinstance(data["subjects"], dict):
        raise ValueError(f"taxonomy.subjects must be object: {path}")
    if "vulns" in data and not isinstance(data["vulns"], dict):
        raise ValueError(f"taxonomy.vulns must be object: {path}")
    return data


def surface_tokens(text: str) -> list[str]:
    """Non-overlapping CJK digrams + English words; stopwords dropped."""
    if not text:
        return []
    out: list[str] = []
    for raw in _WORD_RE.findall(text.lower()):
        if any("\u4e00" <= ch <= "\u9fff" for ch in raw):
            i = 0
            while i < len(raw):
                if i + 1 < len(raw):
                    out.append(raw[i : i + 2])
                    i += 2
                else:
                    out.append(raw[i])
                    i += 1
        else:
            out.append(raw)
    return [t for t in out if t and t not in STOPWORDS]


def _alias_table(taxonomy: dict[str, Any] | None) -> list[tuple[str, str, str, list[str]]]:
    """Longest-alias first: (alias_lower, subject_key, group_key, subject_core)."""
    rows: list[tuple[str, str, str, list[str]]] = []
    if not taxonomy:
        return rows
    subjects = taxonomy.get("subjects") or {}
    for sk, spec in subjects.items():
        if not isinstance(spec, dict):
            continue
        core = [str(x) for x in (spec.get("core") or []) if x]
        groups = spec.get("groups") or {}
        if not isinstance(groups, dict):
            continue
        for gk, aliases in groups.items():
            if not isinstance(aliases, (list, tuple)):
                continue
            cleaned = [str(a).strip() for a in aliases if a and str(a).strip()]
            if len(cleaned) < 2:
                continue
            for a in cleaned:
                rows.append((a.lower(), sk, str(gk), core))
    rows.sort(key=lambda r: len(r[0]), reverse=True)
    return rows


def split_query(query: str, taxonomy: dict[str, Any] | None = None) -> SplitQuery:
    q = (query or "").strip()
    if not q:
        return SplitQuery(core=[], qualifier=[], note="empty query")

    for alias, sk, gk, core in _alias_table(taxonomy):
        idx = q.lower().find(alias)
        if idx < 0:
            continue
        before = q[:idx]
        after = q[idx + len(alias) :]
        remainder = f"{before} {after}".strip()
        core_tokens = surface_tokens(remainder) if remainder else []
        if not core_tokens:
            core_tokens = []
            for c in core:
                core_tokens.extend(surface_tokens(c))
            seen: set[str] = set()
            deduped: list[str] = []
            for t in core_tokens:
                if t in seen:
                    continue
                seen.add(t)
                deduped.append(t)
            core_tokens = deduped
        qual_tokens = surface_tokens(alias)
        group_extra = surface_tokens(gk)
        for t in group_extra:
            if t not in qual_tokens:
                qual_tokens.append(t)
        return SplitQuery(
            core=core_tokens,
            qualifier=qual_tokens,
            subject=sk,
            group=gk,
        )

    # subject core alias alone (no group)
    if taxonomy:
        subjects = taxonomy.get("subjects") or {}
        best: tuple[str, str, list[str]] | None = None
        for sk, spec in subjects.items():
            if not isinstance(spec, dict):
                continue
            core = [str(x) for x in (spec.get("core") or []) if x]
            for c in sorted(core, key=len, reverse=True):
                if c.lower() in q.lower():
                    cand = (c, sk, core)
                    if best is None or len(c) > len(best[0]):
                        best = cand
        if best is not None:
            c, sk, core = best
            idx = q.lower().find(c.lower())
            remainder = f"{q[:idx]} {q[idx + len(c):]}".strip()
            core_tokens = surface_tokens(remainder)
            for term in core:
                for t in surface_tokens(term):
                    if t not in core_tokens:
                        core_tokens.append(t)
            return SplitQuery(core=core_tokens, qualifier=[], subject=sk)

    return SplitQuery(
        core=surface_tokens(q),
        qualifier=[],
        note="no taxonomy group; plain surface match",
    )


def entry_token_bag(entry: dict[str, Any]) -> dict[str, int]:
    """Weighted multiset of tokens from the allowed match surface."""
    bag: dict[str, int] = {}

    def add(text: str, weight: int) -> None:
        for t in surface_tokens(text):
            bag[t] = bag.get(t, 0) + weight

    add(str(entry.get("title") or ""), _FIELD_WEIGHT["title"])
    add(str(entry.get("description") or ""), _FIELD_WEIGHT["description"])
    tags = entry.get("tags") or []
    if isinstance(tags, list):
        add(" ".join(str(t) for t in tags), _FIELD_WEIGHT["tags"])
    validation = entry.get("validation")
    if isinstance(validation, dict):
        add(str(validation.get("signal") or ""), _FIELD_WEIGHT["validation"])
        reject = validation.get("reject") or []
        if isinstance(reject, list):
            add(" ".join(str(x) for x in reject), _FIELD_WEIGHT["validation"])
    return bag


def _coverage(needed: list[str], bag: dict[str, int]) -> float:
    if not needed:
        return 1.0
    hit = sum(1 for t in needed if t in bag)
    return hit / len(needed)


def _score(needed: list[str], bag: dict[str, int]) -> float:
    if not needed:
        return 0.0
    return sum(bag.get(t, 0) for t in needed) / max(1, len(needed))


def judge_entry(
    entry: dict[str, Any],
    split: SplitQuery,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> EntryVerdict:
    bag = entry_token_bag(entry)
    core_cov = _coverage(split.core, bag)
    core_set = set(split.core)
    qual_need = [
        t for t in split.qualifier
        if t not in core_set and t not in _QUALIFIER_NOISE
    ]
    qual_hit = True
    if qual_need:
        qual_hit = any(t in bag for t in qual_need)
    elif split.qualifier:
        # only noise/overlap tokens — treat as no distinctive qualifier
        qual_hit = True
    score = round(_score(split.core + split.qualifier, bag), 3)
    reasons: list[str] = [
        f"core={core_cov:.2f} need={','.join(split.core) or '—'}",
        f"qualifier={'hit' if qual_hit else 'miss'} "
        f"need={','.join(qual_need) or '—'}",
    ]
    if core_cov >= threshold and qual_hit:
        state = HIT
    elif core_cov >= threshold and not qual_hit:
        state = WEAK
    else:
        state = MISS
    return EntryVerdict(
        entry_id=str(entry.get("id") or ""),
        state=state,
        core_coverage=round(core_cov, 3),
        qualifier_hit=qual_hit,
        score=score,
        reasons=reasons,
    )


def check_scope(
    query: str,
    entries: Iterable[dict[str, Any]],
    *,
    taxonomy: dict[str, Any] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    excluded: int = 0,
) -> CheckResult:
    split = split_query(query, taxonomy)
    verdicts = [
        judge_entry(e, split, threshold=threshold) for e in entries
    ]
    verdicts.sort(key=lambda v: (0 if v.state == HIT else 1 if v.state == WEAK else 2, -v.score, v.entry_id))
    if any(v.state == HIT for v in verdicts):
        state = HIT
        code = 0
    elif any(v.state == WEAK for v in verdicts):
        state = WEAK
        code = 1
    else:
        state = MISS
        code = 1
    return CheckResult(
        state=state,
        exit_code=code,
        query=query,
        split=split,
        verdicts=verdicts,
        excluded=excluded,
    )


def diagnose_variants(
    query: str,
    entries: Iterable[dict[str, Any]],
    variants: list[str],
    *,
    taxonomy: dict[str, Any] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[str, int, list[CheckResult]]:
    """Return (verdict_label, exit_code, per-variant CheckResults)."""
    cleaned = [v.strip() for v in variants if v and v.strip()]
    if len(cleaned) < 2:
        return ("need_variants", 2, [])
    results = [
        check_scope(v, entries, taxonomy=taxonomy, threshold=threshold)
        for v in cleaned
    ]
    if any(r.state == HIT for r in results):
        return ("叫法缺口", 0, results)
    if all(r.state == MISS for r in results):
        return ("内容缺口", 1, results)
    if any(r.state == WEAK for r in results):
        return ("无法归因", 3, results)
    return ("内容缺口", 1, results)


def default_variants_for_query(
    query: str, taxonomy: dict[str, Any] | None
) -> list[str]:
    split = split_query(query, taxonomy)
    if not taxonomy or not split.subject or not split.group:
        return []
    spec = (taxonomy.get("subjects") or {}).get(split.subject) or {}
    groups = spec.get("groups") or {}
    aliases = groups.get(split.group) or []
    out = [str(a).strip() for a in aliases if a and str(a).strip()]
    if query.strip() and query.strip() not in out:
        out.insert(0, query.strip())
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for a in out:
        k = a.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(a)
    return uniq
