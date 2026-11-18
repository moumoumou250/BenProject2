"""Standalone PTY host process for ``ben console new``.

Env:
  BEN_CONSOLE_NAME, BEN_CONSOLE_BASE, BEN_CONSOLE_LOG,
  BEN_CONSOLE_SOCK, BEN_CONSOLE_ARGV (JSON list), BEN_CONSOLE_CWD
"""
from __future__ import annotations

import json
import os
import pty
import select
import socket
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

_BUF_BYTES = 1 * 1024 * 1024


def main() -> int:
    name = os.environ["BEN_CONSOLE_NAME"]
    log_path = Path(os.environ["BEN_CONSOLE_LOG"])
    sock_path = Path(os.environ["BEN_CONSOLE_SOCK"])
    cwd = Path(os.environ.get("BEN_CONSOLE_CWD") or ".")
    argv = json.loads(os.environ["BEN_CONSOLE_ARGV"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        try:
            sock_path.unlink()
        except OSError:
            pass

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)

    ring: deque[bytes] = deque()
    ring_size = 0
    ring_lock = threading.Lock()
    log_fh = open(log_path, "ab", buffering=0)
    stop = threading.Event()

    def reader():
        nonlocal ring_size
        while not stop.is_set():
            try:
                r, _, _ = select.select([master], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not r:
                if proc.poll() is not None:
                    break
                continue
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            try:
                log_fh.write(data)
            except OSError:
                pass
            with ring_lock:
                ring.append(data)
                ring_size += len(data)
                while ring_size > _BUF_BYTES and ring:
                    old = ring.popleft()
                    ring_size -= len(old)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    os.chmod(sock_path, 0o600)
    server.listen(8)
    server.settimeout(0.5)

    def handle(conn: socket.socket):
        try:
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            if not buf:
                return
            req = json.loads(buf.decode("utf-8").splitlines()[0])
            op = req.get("op")
            if op == "status":
                resp = {"ok": True, "name": name, "pid": proc.pid, "alive": proc.poll() is None}
            elif op == "send":
                text = req.get("text") or ""
                if not text.endswith("\n"):
                    text += "\n"
                os.write(master, text.encode("utf-8", errors="replace"))
                resp = {"ok": True}
            elif op == "capture":
                lines = int(req.get("lines") or 50)
                with ring_lock:
                    raw = b"".join(ring)
                text = raw.decode("utf-8", errors="replace")
                parts = text.splitlines()
                resp = {"ok": True, "text": "\n".join(parts[-max(1, lines):])}
            elif op == "kill":
                stop.set()
                try:
                    proc.terminate()
                except OSError:
                    pass
                resp = {"ok": True}
            else:
                resp = {"ok": False, "error": f"unknown op {op!r}"}
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            try:
                conn.sendall((json.dumps({"ok": False, "error": str(exc)}) + "\n").encode("utf-8"))
            except OSError:
                pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    try:
        while not stop.is_set():
            if proc.poll() is not None and not t.is_alive():
                # Accept one last round of clients then exit
                try:
                    conn, _ = server.accept()
                    handle(conn)
                except socket.timeout:
                    break
                continue
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            handle(conn)
            if stop.is_set():
                break
    finally:
        stop.set()
        try:
            server.close()
        except OSError:
            pass
        try:
            sock_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            log_fh.close()
        except OSError:
            pass
        try:
            os.close(master)
        except OSError:
            pass
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
