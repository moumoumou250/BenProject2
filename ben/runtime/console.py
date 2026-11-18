"""PTY console sessions for foreign interactive CLIs."""
from __future__ import annotations

import json
import os
import re
import select
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from ben import config
from ben.core import paths
from ben.core.errors import FGError
from ben.core.io import atomic_write_json, now_iso, read_json

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\].*?\x07|\x1b[PX^_].*?\x1b\\")
_BUF_BYTES = 1 * 1024 * 1024


def console_root(base: Path) -> Path:
    """PTY session dir — under the runtime root, never at the base dir.

    Pure path computation: readers (`list_consoles`, `kill_console`) must not
    create a directory just by looking, and writers don't need us to — the
    console host mkdirs the socket dir, and ``atomic_write_json`` mkdirs the
    parent of ``sessions.json``.

    It used to be ``<base>/console``, which put a socket directory next to the
    source tree whenever a console was hosted from a repo root.
    """
    return paths.output_dir(base) / "console"


def _sessions_path(base: Path) -> Path:
    return console_root(base) / "sessions.json"


def _sock_path(base: Path, name: str) -> Path:
    return console_root(base) / f"{name}.sock"


def _log_path(base: Path, name: str) -> Path:
    logs = paths.logs_dir(base, create=True)
    return logs / f"c-{name}.raw"


def _load_sessions(base: Path) -> dict:
    path = _sessions_path(base)
    if not path.exists():
        return {"version": 1, "sessions": {}}
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return {"version": 1, "sessions": {}}
    if not isinstance(data, dict):
        return {"version": 1, "sessions": {}}
    data.setdefault("version", 1)
    data.setdefault("sessions", {})
    return data


def _save_sessions(base: Path, data: dict) -> None:
    atomic_write_json(_sessions_path(base), data)


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _pty_available() -> bool:
    """A console host is useless without /dev/ptmx.

    Note this does NOT require the *caller* to own a terminal: ``openpty()``
    only needs kernel devpts + /dev/ptmx, so cron/CI can still host consoles.
    Only locked-down containers and sandboxes that mask /dev/ptmx fail here.
    """
    return os.path.exists("/dev/ptmx")


def start_console(base: Path, name: str, argv: list[str], *, cwd: Path | None = None) -> dict:
    """Spawn a console_host process for ``name`` running ``argv``."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise FGError("console name must match [A-Za-z0-9_.-]+")
    if not argv:
        raise FGError("console command required")
    if not _pty_available():
        raise FGError(
            "no pseudo-terminal support: /dev/ptmx is missing, so a PTY console "
            "cannot be created here. `ben console` only needs this for hosting "
            "interactive CLIs (`status`/`graph`/`auto`/`view` work without it). "
            "In Docker run with `-t` and a devpts mount; in a sandbox, run the "
            "command outside the restricted environment."
        )
    base = Path(base).resolve()
    data = _load_sessions(base)
    existing = data["sessions"].get(name)
    if isinstance(existing, dict):
        sock = Path(existing.get("sock") or _sock_path(base, name))
        if sock.exists() and _ping(sock):
            raise FGError(f"console {name!r} already running")
    host_mod = "ben.runtime.console_host"
    log = _log_path(base, name)
    sock = _sock_path(base, name)
    if sock.exists():
        try:
            sock.unlink()
        except OSError:
            pass
    env = dict(os.environ)
    env["BEN_CONSOLE_NAME"] = name
    env["BEN_CONSOLE_BASE"] = str(base)
    env["BEN_CONSOLE_LOG"] = str(log)
    env["BEN_CONSOLE_SOCK"] = str(sock)
    env["BEN_CONSOLE_ARGV"] = json.dumps(argv)
    env["BEN_CONSOLE_CWD"] = str(Path(cwd or base).resolve())
    # The host runs as ``-m ben.runtime.console_host`` from the graph dir, which
    # is usually NOT the repo root — without this the import fails and the child
    # dies before it can bind its socket.
    pkg_root = Path(__file__).resolve().parents[2]
    existing_pp = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(pkg_root) + (os.pathsep + existing_pp if existing_pp else "")
    )
    err_log = log.with_suffix(".host.err")
    with open(err_log, "ab", buffering=0) as err_fh:
        proc = subprocess.Popen(
            [config.get("BEN_PYTHON"), "-m", host_mod],
            cwd=str(base),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=err_fh,
            start_new_session=True,
        )
    # Wait briefly for the socket
    deadline = time.time() + 5
    while time.time() < deadline:
        if sock.exists() and _ping(sock):
            break
        time.sleep(0.05)
    else:
        proc.poll()
        detail = ""
        try:
            tail = err_log.read_text(encoding="utf-8", errors="replace").strip()
            if tail:
                detail = f" — host stderr: {tail.splitlines()[-1][:300]}"
        except OSError:
            pass
        raise FGError(
            f"console {name!r} failed to open socket at {sock}{detail}"
        )
    entry = {
        "name": name,
        "pid": proc.pid,
        "argv": argv,
        "sock": str(sock),
        "log": str(log),
        "started_at": now_iso(),
    }
    data["sessions"][name] = entry
    _save_sessions(base, data)
    return entry


def list_consoles(base: Path) -> list[dict]:
    base = Path(base).resolve()
    data = _load_sessions(base)
    rows = []
    for name, entry in sorted(data.get("sessions", {}).items()):
        if not isinstance(entry, dict):
            continue
        sock = Path(entry.get("sock") or _sock_path(base, name))
        alive = sock.exists() and _ping(sock)
        rows.append({**entry, "alive": alive, "backend": "console"})
    return rows


def kill_console(base: Path, name: str) -> bool:
    base = Path(base).resolve()
    data = _load_sessions(base)
    entry = data["sessions"].get(name)
    if not isinstance(entry, dict):
        return False
    sock = Path(entry.get("sock") or _sock_path(base, name))
    if sock.exists():
        try:
            _rpc(sock, {"op": "kill"})
        except FGError:
            pass
    data["sessions"].pop(name, None)
    _save_sessions(base, data)
    try:
        sock.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def send_console(base: Path, name: str, text: str) -> None:
    base = Path(base).resolve()
    data = _load_sessions(base)
    entry = data["sessions"].get(name) or {"sock": str(_sock_path(base, name))}
    sock = Path(entry.get("sock") or _sock_path(base, name))
    if not sock.exists():
        raise FGError(f"console session not found: {name}")
    _rpc(sock, {"op": "send", "text": text})


def capture_console(base: Path, name: str, lines: int = 120) -> str:
    """Prefer the write-through log (works even if the socket is dead)."""
    base = Path(base).resolve()
    data = _load_sessions(base)
    entry = data["sessions"].get(name) or {}
    log = Path(entry.get("log") or _log_path(base, name))
    if log.exists():
        try:
            raw = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            raw = ""
        cleaned = strip_ansi(raw)
        parts = cleaned.splitlines()
        return "\n".join(parts[-max(1, lines):])
    sock = Path(entry.get("sock") or _sock_path(base, name))
    if sock.exists():
        resp = _rpc(sock, {"op": "capture", "lines": lines})
        return str(resp.get("text") or "")
    raise FGError(f"console session not found: {name}")


def console_log_path(base: Path, name: str) -> Path:
    """Write-through log of a session (session override, else the default).

    Exposed so interactive viewers can tail the raw stream incrementally
    instead of re-reading the whole capture on every poll.
    """
    base = Path(base).resolve()
    entry = (_load_sessions(base)["sessions"].get(name)) or {}
    return Path(entry.get("log") or _log_path(base, name))


def _ping(sock: Path) -> bool:
    try:
        resp = _rpc(sock, {"op": "status"}, timeout=0.5)
        return bool(resp.get("ok"))
    except FGError:
        return False


def _rpc(sock: Path, payload: dict, timeout: float = 5.0) -> dict:
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(str(sock))
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = client.recv(65536)
            if not chunk:
                break
            buf += chunk
        client.close()
    except OSError as exc:
        raise FGError(f"console socket error: {exc}") from exc
    if not buf:
        raise FGError("console socket returned empty response")
    try:
        return json.loads(buf.decode("utf-8").splitlines()[0])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FGError(f"console socket bad response: {exc}") from exc
