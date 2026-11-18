"""AI peers registry + peers/send/capture (proc workers + PTY consoles)."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from ben import config
from ben.consts import AI_CHANNEL_NAME, PEERS_FILE, PEER_NAME_RE
from ben.core import paths
from ben.core.errors import FGError
from ben.core.io import atomic_write_json, now_iso, read_json
from ben.core.store import Store
from ben.runtime.agents import AgentRegistry, fleet_registry_root
from ben.runtime.console import capture_console, list_consoles, send_console

_PROC_RE = re.compile(r"^w-[A-Za-z0-9_.-]+$")
_CONSOLE_RE = re.compile(r"^c-[A-Za-z0-9_.-]+$")
_LEGACY_PANE_RE = re.compile(r"^[^:]+:\d+(\.\d+)?$")

_MIGRATE_HINT = (
    "legacy sess:win.pane targets are no longer supported; run "
    "`ben console new <name> -- <cmd>` or use a worker target `w-<name>`"
)


def _peers_path(store: Store) -> Path:
    return store.root / PEERS_FILE


def _default_peers(store: Store) -> dict:
    return {
        "version": 1,
        "channel": str((store.root / AI_CHANNEL_NAME).resolve()),
        "peers": {},
    }


def _load_peers(store: Store) -> dict:
    path = _peers_path(store)
    if not path.exists():
        return _default_peers(store)
    try:
        data = read_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError) as exc:
        raise FGError(f"cannot read peers config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise FGError(f"invalid peers config at {path}")
    data.setdefault("version", 1)
    data.setdefault("channel", str((store.root / AI_CHANNEL_NAME).resolve()))
    data.setdefault("peers", {})
    if not isinstance(data["version"], int) or isinstance(data["version"], bool):
        raise FGError(f"invalid peers config at {path}: version must be an integer")
    if not isinstance(data["channel"], str) or not data["channel"].strip():
        raise FGError(f"invalid peers config at {path}: channel must be a non-empty string")
    if not isinstance(data["peers"], dict):
        raise FGError(f"invalid peers config at {path}: peers must be an object")
    for name, peer in data["peers"].items():
        if not isinstance(name, str) or not PEER_NAME_RE.fullmatch(name):
            raise FGError(f"invalid peers config at {path}: invalid peer name {name!r}")
        if not isinstance(peer, dict) or not isinstance(peer.get("target"), str):
            raise FGError(f"invalid peers config at {path}: peer {name!r} needs a target")
    return data


def _save_peers(store: Store, data: dict) -> None:
    with store.locked():
        atomic_write_json(_peers_path(store), data)


def _target_backend(target: str) -> str:
    if _PROC_RE.fullmatch(target):
        return "proc"
    if _CONSOLE_RE.fullmatch(target):
        return "console"
    if _LEGACY_PANE_RE.fullmatch(target):
        return "legacy"
    return "unknown"


def _discover_rows(store: Store) -> list[dict]:
    rows: list[dict] = []
    registry = AgentRegistry(fleet_registry_root(Path.cwd()))
    for r in registry.status():
        rows.append({
            "target": r["name"] if r["name"].startswith("w-") else f"w-{r['name']}",
            "backend": "proc",
            "command": "ben-worker",
            "title": r["name"],
            "active": r["alive"],
            "pid": r["pid"],
            "log": r["log"],
        })
    for r in list_consoles(Path.cwd()):
        rows.append({
            "target": f"c-{r['name']}",
            "backend": "console",
            "command": " ".join(r.get("argv") or []),
            "title": r["name"],
            "active": r.get("alive"),
            "pid": r.get("pid"),
            "log": r.get("log"),
        })
    return rows


def cmd_peers(args) -> int:
    store = Store(Path(args.store))
    store.require()

    if args.discover:
        rows = _discover_rows(store)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if not rows:
            print("no worker or console sessions found")
            return 0
        print("sessions:")
        for r in rows:
            marker = "*" if r.get("active") else " "
            print(
                f"  {marker} {r['target']:<16} backend={r['backend']:<8} "
                f"cmd={r.get('command')}"
            )
        print(
            "\nAuthorize explicitly before sending, for example:\n"
            "  ben peers --add harley --target w-c01 --sender \"Codex/api2-4\"\n"
            "  ben peers --add claude --target c-main --sender \"ben-agent\""
        )
        return 0

    data = _load_peers(store)
    peers = data["peers"]

    if args.add:
        name = args.add.strip()
        if not PEER_NAME_RE.match(name):
            raise FGError("peer name must contain only letters, numbers, '.', '_' or '-'")
        if not args.target:
            raise FGError("--target is required with --add")
        backend = _target_backend(args.target)
        if backend == "legacy":
            raise FGError(_MIGRATE_HINT)
        if backend == "unknown":
            raise FGError(
                f"unsupported target {args.target!r}; use w-<name> or c-<name>. {_MIGRATE_HINT}"
            )
        if args.channel:
            data["channel"] = str(Path(args.channel).expanduser())
        peers[name] = {
            "target": args.target,
            "sender": args.sender or config.get("FGC_SENDER") or "ben-agent",
            "created_at": now_iso(),
            "note": args.note or None,
        }
        _save_peers(store, data)
        print(f"authorized peer {name}: target={args.target} sender={peers[name]['sender']}")
        return 0

    if args.remove:
        name = args.remove.strip()
        if name not in peers:
            raise FGError(f"peer not configured: {name}")
        del peers[name]
        _save_peers(store, data)
        print(f"removed peer {name}")
        return 0

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"peer config: {_peers_path(store)}")
    print(f"shared log:  {data.get('channel')}")
    if not peers:
        print("(no authorized peers)")
        print("run `ben peers --discover` to list workers/consoles, then authorize one with --add")
        return 0
    print("authorized peers:")
    for name, peer in sorted(peers.items()):
        note = f" note={peer.get('note')!r}" if peer.get("note") else ""
        print(f"  {name:<16} target={peer.get('target')} sender={peer.get('sender')}{note}")
    return 0


def cmd_send(args) -> int:
    store = Store(Path(args.store))
    store.require()
    data = _load_peers(store)
    peers = data["peers"]
    peer = peers.get(args.peer)
    if peer is None:
        raise FGError(
            f"peer not configured: {args.peer}. Run `ben peers` to see authorized peers."
        )
    target = peer.get("target")
    if not target:
        raise FGError(f"peer {args.peer} has no target")
    backend = _target_backend(target)
    if backend == "legacy":
        raise FGError(_MIGRATE_HINT)
    if backend == "unknown":
        raise FGError(f"unsupported target {target!r}. {_MIGRATE_HINT}")

    if args.message:
        body = " ".join(args.message).strip()
    else:
        body = sys.stdin.read().strip()
    if not body:
        raise FGError("empty message")

    if args.raw:
        message = body
    else:
        stamp = time.strftime("%Y-%m-%d %H:%M")
        sender = args.sender or peer.get("sender") or config.get("FGC_SENDER") or "ben-agent"
        message = f"[{stamp}][{sender}] {body}"

    if not args.no_log:
        channel = Path(args.channel or data.get("channel") or (store.root / AI_CHANNEL_NAME))
        channel.parent.mkdir(parents=True, exist_ok=True)
        with open(channel, "a", encoding="utf-8") as fh:
            fh.write(message + "\n")

    sender = args.sender or peer.get("sender") or config.get("FGC_SENDER") or "ben-agent"
    if backend == "proc":
        store.add_hint(content=message, creator=sender, to=target)
    else:
        # console: paste-equivalent via socket + LF cadence
        send_console(Path.cwd(), target[2:], message)
        time.sleep(config.get_float("AI_SEND_INITIAL_DELAY"))
        send_console(Path.cwd(), target[2:], "\n")
        time.sleep(config.get_float("AI_SEND_SUBMIT_DELAY"))
        send_console(Path.cwd(), target[2:], "\n")
    print(f"sent to {args.peer} ({target}): {message}")
    return 0


def cmd_capture(args) -> int:
    store = Store(Path(args.store))
    store.require()
    data = _load_peers(store)
    peer = data["peers"].get(args.peer)
    if peer is None:
        raise FGError(
            f"peer not configured: {args.peer}. Run `ben peers` to see authorized peers."
        )
    target = peer.get("target")
    if not target:
        raise FGError(f"peer {args.peer} has no target")
    backend = _target_backend(target)
    if backend == "legacy":
        raise FGError(_MIGRATE_HINT)
    if backend == "unknown":
        raise FGError(f"unsupported target {target!r}. {_MIGRATE_HINT}")
    if args.lines < 1 or args.lines > 2000:
        raise FGError("--lines must be between 1 and 2000")

    if backend == "proc":
        text = AgentRegistry(fleet_registry_root(Path.cwd())).logs_tail(
            target, args.lines
        )
    else:
        text = capture_console(Path.cwd(), target[2:], lines=args.lines)
    print(text)

    if args.log:
        channel = Path(args.channel or data.get("channel") or (store.root / AI_CHANNEL_NAME))
        channel.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M")
        with open(channel, "a", encoding="utf-8") as fh:
            fh.write(
                f"[{stamp}][ben-capture] peer={args.peer} "
                f"target={target} lines={args.lines}\n"
            )
            fh.write(text + "\n")
    return 0
