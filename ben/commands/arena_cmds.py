"""flag submission and arena platform commands."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ben.core.errors import FGError
from ben.core.store import Store


def _load_arena_module():
    # arena.py stays a standalone stdlib-only module: external callers may
    # load it directly from its file path via importlib, so it must not
    # import the ben package.
    import ben.arena as module
    # arena.py cannot subclass FGError at definition time — yet every
    # bench/auto caller guards with `except FGError`, and an uncaught
    # ArenaError kills the whole loop (seen live: HTTP 409 "max active
    # challenge instances" crashed bench). Rebind it as a direct FGError
    # subclass after import: raising sites resolve the name through module
    # globals, so this takes effect immediately, and inheriting the original
    # class keeps its custom __init__ (code/status/detail) and zero-arg
    # super() closure intact. Rebinding is idempotent.
    if not issubclass(module.ArenaError, FGError):
        module.ArenaError = type("ArenaError", (FGError, module.ArenaError), {})
    return module


def _arena_client(store: Store):
    arena = _load_arena_module()
    try:
        return arena.ArenaClient.load(store.root)
    except arena.ArenaError as exc:
        raise FGError(str(exc)) from exc


def _find_flag_fact(store: Store, value: str) -> dict | None:
    for f in store.list_facts():
        if f.get("kind") != "flag":
            continue
        if (f.get("data") or {}).get("value") == value:
            return f
    return None


def cmd_flag(args) -> int:
    store = Store(Path(args.store))
    store.require()
    value = args.value.strip()
    if not value:
        raise FGError("flag value cannot be empty")
    existing = _find_flag_fact(store, value)
    if existing is not None:
        d = existing.get("data") or {}
        raise FGError(
            f"flag already recorded as {existing['id']} "
            f"(status={d.get('status', 'recorded')}, challenge={d.get('challenge', '?')})"
        )
    challenge = (args.challenge or "").strip()
    description = f"flag captured: {value}" + (f" (challenge {challenge})" if challenge else "")
    fact = store.add_fact(
        description=description,
        creator=args.creator,
        source_intent=None,
        title=args.title or "flag",
        kind="flag",
        data={"value": value, "challenge": challenge, "status": "recorded"},
    )
    print(f"{fact['id']} recorded")
    if not args.submit:
        print("(not submitted; pass --submit to send it via the arena API)")
        return 0
    client = _arena_client(store)
    if not challenge:
        print("ben: warning: no --challenge given; submit endpoint may need it", file=sys.stderr)
    try:
        reply = client.submit_flag(challenge or "-", value)
    except FGError:
        raise
    except Exception as exc:  # ArenaError subclasses Exception
        store.update_flag_fact(fact["id"], "rejected", str(exc))
        raise FGError(f"submit failed, flag kept as {fact['id']} (recorded): {exc}") from exc
    raw = json.dumps(reply.get("result", {}), ensure_ascii=False)
    accepted = reply.get("status") == 200
    status = "submitted" if accepted else "rejected"
    store.update_flag_fact(fact["id"], status, raw[:500])
    print(f"{fact['id']} {status}: {raw[:300]}")
    return 0 if accepted else 1


def cmd_arena(args) -> int:
    store = Store(Path(args.store))
    if args.action == "init":
        arena = _load_arena_module()
        path = arena.ArenaClient.config_path(store.root)
        if path.exists():
            raise FGError(f"arena config already exists: {path}")
        written = arena.ArenaClient.write_template(store.root)
        print(f"wrote {written} — fill in the official API base_url/endpoints, "
              f"then export BEN_ARENA_TOKEN")
        return 0
    store.require()
    client = _arena_client(store)
    action = args.action
    if action == "challenges":
        reply = client.list_challenges()
    elif action == "start":
        reply = client.start_challenge(args.challenge_id)
    elif action == "stop":
        reply = client.close_challenge(args.challenge_id)
    elif action == "submit":
        reply = client.submit_flag(args.challenge_id, args.flag)
    elif action == "hint":
        print("ben: note — official rules deduct score for hints (-10%); "
              "only ask when genuinely stuck", file=sys.stderr)
        reply = client.get_hint(args.challenge_id)
    else:
        raise FGError(f"unknown arena action {action!r}")
    print(json.dumps(reply.get("result", {}), ensure_ascii=False, indent=2))
    return 0
