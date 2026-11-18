"""init/status/graph/validate/frontier/pick/fact/intent/hint commands."""
from __future__ import annotations

import json
from pathlib import Path

from ben.agents.factory import _worker_id
from ben.commands.util import _assert_safe_store_root, _read_doc_arg, parse_from
from ben.core.errors import FGError
from ben.core.graph import build_graph_view, frontier, is_open, validate_graph
from ben.core.schema import parse_kv_pairs
from ben.core.store import Store
from ben.agents.prompt import render_graph_text
from ben.report.status import render_status


def cmd_init(args) -> int:
    store = Store(Path(args.store))
    if store.exists() and not args.force:
        raise FGError(f"graph exists at {store.root}; use --force to overwrite")
    if args.force and store.root.exists():
        import shutil
        _assert_safe_store_root(store.root, "overwrite")
        # `--force` is an explicit destructive operation.  Do not hold the
        # graph's lock while deleting that lock file itself; another process
        # waiting on the old inode would otherwise be detached from the new
        # graph.  Normal (non-force) initialization is serialized in Store.init.
        shutil.rmtree(store.root)
    origin = args.origin or ""
    goal = args.goal
    if not goal:
        raise FGError("--goal is required")
    store.init(origin=origin, goal=goal)
    print(f"initialized fact graph at {store.root}")
    print(f"goal: {goal}")
    return 0


def cmd_status(args) -> int:
    store = Store(Path(args.store))
    store.require()
    print(render_status(store))
    return 0


def cmd_graph(args) -> int:
    store = Store(Path(args.store))
    store.require()
    if args.format == "json":
        print(json.dumps(build_graph_view(store), ensure_ascii=False, indent=2))
    else:
        print(render_graph_text(store))
    return 0


def cmd_validate(args) -> int:
    store = Store(Path(args.store))
    store.require()
    errors = validate_graph(store)
    if errors:
        print(f"graph invalid: {len(errors)} error(s)")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"graph valid: {store.root}")
    return 0


def cmd_frontier(args) -> int:
    store = Store(Path(args.store))
    store.require()
    fr = frontier(store)
    if not fr:
        print("(no ready intents)")
        return 0
    for i in fr:
        mark = ""
        if i["status"] == "claimed":
            mark = f"  [claimed: {i['worker']}]"
        elif i["requires_confirmation"] and not i["confirmed_at"]:
            mark = "  [needs confirmation]"
        print(f"{i['id']}\tfrom={','.join(i['from'])}\t{i['description']}{mark}")
    return 0


def cmd_pick(args) -> int:
    store = Store(Path(args.store))
    store.require()
    fr = frontier(store)
    worker = args.worker or _worker_id("agent") if args.claim else None
    pool = []
    if fr:
        # `frontier` shows claimed work first for observability, but a worker
        # asking to claim should skip another worker's lease and choose the
        # next unclaimed item instead of failing on an unrelated lease.
        pool = [
            i for i in fr
            if not args.claim or not i.get("worker") or i.get("worker") == worker
        ]
    if not pool and args.any:
        # escape hatch: include intents not yet ready (e.g. awaiting confirmation)
        pool = [i for i in store.list_intents() if is_open(i)]
    if not pool:
        print("(nothing ready; pass --any to include unconfirmed/blocked open intents)")
        return 0
    chosen = pool[0]
    if args.claim:
        assert worker is not None
        chosen = store.claim_intent(chosen["id"], worker)
    print(chosen["id"])
    return 0


def cmd_fact(args) -> int:
    store = Store(Path(args.store))
    store.require()
    fact = store.add_fact(
        description=args.description,
        creator=args.creator,
        source_intent=args.from_intent,
        title=args.title,
        doc=_read_doc_arg(args),
        kind=args.kind,
        data=parse_kv_pairs(args.data),
    )
    print(fact["id"])
    if args.json:
        print(json.dumps(fact, ensure_ascii=False))
    return 0


def cmd_intent(args) -> int:
    store = Store(Path(args.store))
    store.require()
    from_ids = parse_from(args.from_)
    intent = store.add_intent(
        from_ids=from_ids,
        description=args.description,
        creator=args.creator,
        requires_confirmation=args.confirm,
        title=args.title,
        doc=_read_doc_arg(args),
    )
    print(intent["id"])
    if args.json:
        print(json.dumps(intent, ensure_ascii=False))
    return 0


def cmd_hint(args) -> int:
    store = Store(Path(args.store))
    store.require()
    if args.list:
        for h in store.list_hints():
            dest = f"\tto={h['to']}" if h.get("to") else ""
            print(f"{h['id']}\t({h['creator']}){dest}\t{h['content']}")
        return 0
    if not args.content:
        raise FGError("hint content required (or use --list)")
    h = store.add_hint(
        content=args.content,
        creator=args.creator,
        to=getattr(args, "to", None),
    )
    print(h["id"])
    return 0
