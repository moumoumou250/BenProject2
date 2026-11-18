"""claim/release/done/confirm/dispatch commands."""
from __future__ import annotations

import os
from pathlib import Path

from ben.agents.dispatch import _dispatch_explore, _dispatch_reason, _dispatch_verify
from ben.agents.factory import _run_blindspot, _run_brainstorm
from ben.commands.util import _read_doc_arg, parse_from
from ben.core.errors import FGError
from ben.core.schema import parse_kv_pairs
from ben.core.store import Store


def cmd_claim(args) -> int:
    store = Store(Path(args.store))
    store.require()
    intent = store.claim_intent(args.id, args.worker)
    print(f"claimed {intent['id']} -> {args.worker}")
    return 0


def cmd_release(args) -> int:
    store = Store(Path(args.store))
    store.require()
    worker = args.worker or f"agent-{os.getpid()}"
    intent = store.release_intent(args.id, worker)
    print(f"released {intent['id']}")
    return 0


def cmd_done(args) -> int:
    store = Store(Path(args.store))
    store.require()
    force = bool(getattr(args, "force", False))
    evidence = getattr(args, "evidence", None)
    # atomic fact-create + conclude (no orphan fact if the intent was already done)
    fact, intent = store.conclude_with_new_fact(
        args.id, args.fact, args.worker, title=args.title, doc=_read_doc_arg(args),
        kind=args.kind, data=parse_kv_pairs(args.data),
        evidence=evidence, force=force,
    )
    if force:
        store.add_hint(
            f"forced conclude of {args.id} by {args.worker} (no machine evidence)",
            args.worker,
        )
    print(f"{args.id} -> {fact['id']}  ({intent['status']})")
    return 0


def cmd_complete(args) -> int:
    store = Store(Path(args.store))
    store.require()
    from_ids = parse_from(args.from_)
    note = args.note or "goal satisfied"
    intent = store.complete_project(from_ids, note, args.worker)
    print(f"project complete via {intent['id']} (goal)")
    return 0


def cmd_confirm(args) -> int:
    store = Store(Path(args.store))
    store.require()
    intent = store.confirm_intent(args.id)
    print(f"confirmed {intent['id']}")
    return 0


def cmd_dispatch(args) -> int:
    store = Store(Path(args.store))
    store.require()
    model = args.model
    timeout = args.timeout
    if not isinstance(model, str) or not model.strip():
        raise FGError("--model cannot be empty")
    if timeout < 1:
        raise FGError("--timeout must be at least 1 second")
    skip = args.skip_permissions
    templates_dir = Path(args.templates)

    cwd = Path.cwd()

    if args.target == "reason":
        return _dispatch_reason(store, templates_dir, model, timeout, skip, cwd, args)
    elif args.target == "verify":
        return _dispatch_verify(store, templates_dir, model, timeout, skip, cwd, args)
    elif args.target == "blindspot":
        return _run_blindspot(store, templates_dir, model, timeout, skip, cwd, args)
    elif args.target == "brainstorm":
        return _run_brainstorm(store, templates_dir, model, timeout, skip, cwd, args)
    else:
        # treat as intent id -> explore
        intent = store.get_intent(args.target)
        return _dispatch_explore(
            store, templates_dir, intent, model, timeout, skip, cwd, args
        )
