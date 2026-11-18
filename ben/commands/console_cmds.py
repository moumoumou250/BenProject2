"""CLI commands: ben console new|list|kill|attach|capture."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from ben.core.errors import FGError
from ben.runtime.console import (
    capture_console, console_log_path, kill_console, list_consoles, send_console,
    start_console, strip_ansi,
)


def _base_from_args(args) -> Path:
    store = getattr(args, "store", None)
    if store:
        return Path(store).resolve().parent
    return Path.cwd()


def _norm_name(name: str) -> str:
    """Accept both ``main`` and the peer-target spelling ``c-main``."""
    name = (name or "").strip()
    return name[2:] if name.startswith("c-") else name


def cmd_console(args) -> int:
    base = _base_from_args(args)
    action = args.console_action
    if action == "new":
        name = _norm_name(args.name)
        argv = list(args.cmd or [])
        if argv and argv[0] == "--":
            argv = argv[1:]
        if not argv:
            raise FGError("usage: ben console new <name> -- <command>...")
        entry = start_console(base, name, argv, cwd=Path.cwd())
        print(f"console c-{name} up  pid={entry['pid']}  log={entry['log']}")
        print(f"  authorize: ben peers --add {name} --target c-{name}")
        return 0
    if action == "list":
        rows = list_consoles(base)
        if args.json:
            import json
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if not rows:
            print("no console sessions")
            return 0
        for r in rows:
            mark = "*" if r.get("alive") else " "
            print(f"  {mark} c-{r['name']:<14} pid={r.get('pid')} log={r.get('log')}")
        return 0
    if action == "kill":
        ok = kill_console(base, _norm_name(args.name))
        print(f"console {_norm_name(args.name)}: {'killed' if ok else 'not found'}")
        return 0 if ok else 1
    if action == "attach":
        return _attach(base, _norm_name(args.name))
    if action == "capture":
        text = capture_console(base, _norm_name(args.name), lines=args.lines)
        print(text)
        return 0
    raise FGError(f"unknown console action {action!r}")


def _attach(base: Path, name: str) -> int:
    """Live view + line input, the tmux `attach`/`capture-pane` equivalent.

    Polls the session's write-through log every 0.5s and prints new bytes
    (ANSI-stripped) — the screen the console TUI is currently showing.
    Lines typed on stdin are forwarded to the PTY. Ctrl-D or Ctrl-C detaches.
    """
    path = console_log_path(base, name)
    try:
        # show a screenful of recent history first, like tmux attach
        sys.stdout.write(capture_console(base, name, lines=40) + "\n")
        sys.stdout.flush()
    except FGError as exc:
        print(f"[console] {exc}", file=sys.stderr)
        return 1
    offset = path.stat().st_size if path.exists() else 0

    stop = threading.Event()

    def _forward() -> None:
        try:
            for line in sys.stdin:
                try:
                    send_console(base, name, line.rstrip("\n"))
                except FGError as exc:
                    print(f"\n[console] send failed: {exc}", file=sys.stderr)
                    break
        finally:
            stop.set()

    print(f"[console] attached to c-{name} — live view; "
          f"type lines to send; Ctrl-D to detach", file=sys.stderr)
    threading.Thread(target=_forward, daemon=True).start()
    try:
        while not stop.is_set():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size < offset:  # log rotated / truncated
                offset = 0
            if size > offset:
                try:
                    with open(path, "rb") as fh:
                        fh.seek(offset)
                        chunk = fh.read(size - offset)
                    offset = size
                except OSError:
                    chunk = b""
                text = strip_ansi(chunk.decode("utf-8", errors="replace"))
                if text:
                    sys.stdout.write(text)
                    sys.stdout.flush()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    print(f"\n[console] detached from c-{name}", file=sys.stderr)
    return 0
