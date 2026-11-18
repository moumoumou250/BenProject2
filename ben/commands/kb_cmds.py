"""Offline knowledge-base commands."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ben.core.errors import FGError


def _load_kb_module():
    import ben.kb as module
    return module


def _kb(args):
    module = _load_kb_module()
    root = Path(args.root) if args.root else module.KnowledgeBase.default_root()
    return module, module.KnowledgeBase(root)


def _parse_only(raw) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for item in raw:
        for part in str(item).replace(",", " ").split():
            p = part.strip()
            if p:
                out.append(p)
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for i in out:
        if i in seen:
            continue
        seen.add(i)
        uniq.append(i)
    return uniq


def _resolve_only(kb, only_ids: list[str]) -> tuple[list[dict], int] | int:
    """Return (entries, excluded) or an exit code (2) after printing error."""
    if not only_ids:
        sys.stderr.write("ben: --only is required and must list at least one kb id\n")
        return 2
    available = {e["id"]: e for e in kb.list_entries()}
    missing = [i for i in only_ids if i not in available]
    if missing:
        sample = sorted(available)[:10]
        more = "..." if len(available) > 10 else ""
        sys.stderr.write(
            f"ben: unknown kb id(s): {', '.join(missing)}\n"
            f"ben: available (sample): {', '.join(sample)}{more}\n"
        )
        return 2
    entries = [available[i] for i in only_ids]
    excluded = len(available) - len(entries)
    return entries, excluded


def _load_taxonomy(module, kb):
    from ben.kb import match as matchmod
    path = kb.root / "taxonomy.json"
    try:
        return matchmod.load_taxonomy(path if path.is_file() else None)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        sys.stderr.write(f"ben: taxonomy error at {path}: {exc}\n")
        return 2


def _parse_variants(args, query: str, taxonomy) -> list[str] | int:
    from ben.kb import match as matchmod
    if args.variants:
        parts = [p.strip() for p in str(args.variants).split(",") if p.strip()]
        return parts
    if args.variants_file:
        path = Path(args.variants_file)
        if not path.is_file():
            sys.stderr.write(f"ben: variants file not found: {path}\n")
            return 2
        lines = [
            ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        return lines
    return matchmod.default_variants_for_query(query, taxonomy)


def _cmd_check(args, module, kb) -> int:
    from ben.kb import match as matchmod

    query = (args.target or "").strip()
    if not query:
        sys.stderr.write("ben: check needs a query\n")
        return 2
    only = _parse_only(args.only)
    resolved = _resolve_only(kb, only)
    if isinstance(resolved, int):
        return resolved
    entries, excluded = resolved
    tax = _load_taxonomy(module, kb)
    if tax == 2:
        return 2
    result = matchmod.check_scope(
        query, entries, taxonomy=tax, excluded=excluded,
    )
    if getattr(args, "kb_json", False):
        payload = {
            "state": result.state,
            "exit_code": result.exit_code,
            "query": result.query,
            "scope": {
                "only": only,
                "excluded": excluded,
                "n": len(entries),
            },
            "split": {
                "core": result.split.core,
                "qualifier": result.split.qualifier,
                "subject": result.split.subject,
                "group": result.split.group,
                "note": result.split.note,
            },
            "verdicts": [
                {
                    "id": v.entry_id,
                    "state": v.state,
                    "core_coverage": v.core_coverage,
                    "qualifier_hit": v.qualifier_hit,
                    "score": v.score,
                    "reasons": v.reasons,
                }
                for v in result.verdicts
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return result.exit_code

    print(f"scope: only={','.join(only)} n={len(entries)} excluded={excluded}")
    if args.show_tokens or result.split.note:
        print(
            f"tokens: core=[{', '.join(result.split.core)}] "
            f"qualifier=[{', '.join(result.split.qualifier)}]"
            + (f" note={result.split.note}" if result.split.note else "")
        )
    for v in result.verdicts:
        print(
            f"{v.entry_id}\t{v.state}\tscore={v.score}\t"
            f"core={v.core_coverage}\tqual={'Y' if v.qualifier_hit else 'N'}"
        )
        for reason in v.reasons:
            print(f"      {reason}")
    print(f"verdict: {result.state}")
    return result.exit_code


def _cmd_diagnose(args, module, kb) -> int:
    from ben.kb import match as matchmod

    query = (args.target or "").strip()
    if not query:
        sys.stderr.write("ben: diagnose needs a query\n")
        return 2
    only = _parse_only(args.only)
    resolved = _resolve_only(kb, only)
    if isinstance(resolved, int):
        return resolved
    entries, excluded = resolved
    tax = _load_taxonomy(module, kb)
    if tax == 2:
        return 2
    variants = _parse_variants(args, query, tax)
    if isinstance(variants, int):
        return variants
    label, code, results = matchmod.diagnose_variants(
        query, entries, variants, taxonomy=tax,
    )
    if getattr(args, "kb_json", False):
        payload = {
            "verdict": label,
            "exit_code": code,
            "query": query,
            "variants": variants,
            "scope": {"only": only, "excluded": excluded, "n": len(entries)},
            "results": [
                {"variant": r.query, "state": r.state, "exit_code": r.exit_code}
                for r in results
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return code

    if code == 2 and label == "need_variants":
        sys.stderr.write(
            "ben: diagnose needs ≥2 variants "
            "(--variants / --variants-file / taxonomy group)\n"
        )
        return 2
    print(f"scope: only={','.join(only)} n={len(entries)} excluded={excluded}")
    print(f"variants: {', '.join(variants)}")
    for r in results:
        print(f"  {r.query!r} → {r.state}")
    print(f"verdict: {label}")
    return code


def cmd_kb(args) -> int:
    module, kb = _kb(args)
    try:
        if args.action == "add":
            detail = args.detail or ""
            if args.detail_file:
                detail = Path(args.detail_file).read_text(encoding="utf-8")
            entry = kb.add(
                title=args.target,
                description=args.description or "",
                detail=detail,
                commands=args.command or [],
                tags=args.tag or [],
                source=args.source or "",
            )
            print(f"{entry['id']}  {entry['title']}")
            return 0
        if args.action == "show":
            print(json.dumps(kb.get(args.target), ensure_ascii=False, indent=2))
            return 0
        if args.action == "list":
            entries = kb.list_entries()
            if args.tag:
                wants = {t.strip().lower() for t in args.tag}
                entries = [
                    e for e in entries
                    if wants & {t.lower() for t in e.get("tags", [])}
                ]
            if not entries:
                print(f"(no kb entries matching tag filter at {kb.root})")
                return 0
            for e in entries:
                tags = ",".join(e.get("tags", []))
                print(f"{e['id']}\t[{tags}]\t{e['title']}")
            return 0
        if args.action == "search":
            tag = args.tag[0] if args.tag else None
            only = _parse_only(args.only) if args.only else None
            if only is not None:
                resolved = _resolve_only(kb, only)
                if isinstance(resolved, int):
                    return resolved
                scoped, excluded = resolved
                # old scorer, id filter only (KB-SCOPE-VERIFY)
                idset = {e["id"] for e in scoped}
                hits = [
                    h for h in kb.search(args.target, tag=tag, limit=max(args.limit, len(idset)))
                    if h["id"] in idset
                ][: args.limit]
                print(f"scope: only={','.join(only)} excluded={excluded}")
            else:
                hits = kb.search(args.target, tag=tag, limit=args.limit)
            if not hits:
                print("(no kb matches — try other keywords, `ben kb list` to browse)")
                return 0
            for h in hits:
                tags = ",".join(h["tags"])
                print(f"{h['id']}\tscore={h['score']}\t[{tags}]\t{h['title']}")
                if h["description"]:
                    print(f"      {h['description'][:100]}")
            print("read full entries with: ben kb show <id>")
            return 0
        if args.action == "check":
            return _cmd_check(args, module, kb)
        if args.action == "diagnose":
            return _cmd_diagnose(args, module, kb)
        if args.action == "import":
            target = Path(args.target)
            if not target.exists():
                raise FGError(f"import path not found: {target}")
            files = sorted(target.glob("*.md")) if target.is_dir() else [target]
            if target.is_dir() and not files:
                raise FGError(f"no .md files under {target}")
            added = 0
            for f in files:
                parsed = module.import_markdown(
                    f, base_tags=args.tag or [], source=str(f),
                )
                entry = kb.add(**parsed)
                print(f"{entry['id']}  {entry['title']}")
                added += 1
            print(f"imported {added} entr{'y' if added == 1 else 'ies'} into {kb.root}")
            return 0
        if args.action == "root":
            print(kb.root)
            return 0
        raise FGError(f"unknown kb action {args.action!r}")
    except module.KBError as exc:
        raise FGError(str(exc)) from exc
