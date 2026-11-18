"""Process registry for ben workers."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from ben.core import paths
from ben.core.errors import FGError
from ben.core.io import atomic_write_json, now_iso, read_json


def _proc_start_key(pid: int) -> str | None:
    """Return a starttime token that uniquely identifies this PID incarnation.

    On Linux this is /proc/<pid>/stat field 22 (1-indexed; after the comm
    field). Without it, a recycled PID looks like a live worker forever.
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as fh:
            rest = fh.read().rsplit(")", 1)[1].split()
        return rest[19]
    except (OSError, IndexError, ValueError):
        return None


def _pid_alive(pid: int, start_key: str | None) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    if start_key is None:
        return True
    current = _proc_start_key(pid)
    if current is None:
        return True
    return current == start_key


class AgentRegistry:
    """File-backed registry of spawned worker processes under ``root``."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs_dir = self.root / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "workers.json"
        self.lock_path = self.root / "workers.json.lock"

    @contextlib.contextmanager
    def _locked(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "workers": {}}
        try:
            data = read_json(self.path)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError):
            return {"version": 1, "workers": {}}
        if not isinstance(data, dict):
            return {"version": 1, "workers": {}}
        data.setdefault("version", 1)
        data.setdefault("workers", {})
        if not isinstance(data["workers"], dict):
            data["workers"] = {}
        return data

    def _save(self, data: dict) -> None:
        atomic_write_json(self.path, data)

    def log_path(self, name: str) -> Path:
        return self.logs_dir / f"{name}.log"

    def alive(self, name: str) -> bool:
        with self._locked():
            entry = self._load()["workers"].get(name)
            if not isinstance(entry, dict):
                return False
            return _pid_alive(int(entry.get("pid") or 0), entry.get("start_key"))

    def reap(self) -> list[str]:
        """Drop dead entries; return names removed."""
        removed: list[str] = []
        with self._locked():
            data = self._load()
            workers = data["workers"]
            for name, entry in list(workers.items()):
                if not isinstance(entry, dict):
                    del workers[name]
                    removed.append(name)
                    continue
                if not _pid_alive(int(entry.get("pid") or 0), entry.get("start_key")):
                    del workers[name]
                    removed.append(name)
            self._save(data)
        return removed

    def spawn(
        self,
        name: str,
        argv: list[str],
        *,
        cwd: Path | str,
        env: dict | None = None,
        meta: dict | None = None,
    ) -> bool:
        """Start a worker. Returns False if a live worker with the same name exists."""
        if not name or not isinstance(name, str):
            raise FGError("worker name required")
        if not argv:
            raise FGError("worker argv required")
        cwd_path = Path(cwd).resolve()
        with self._locked():
            data = self._load()
            existing = data["workers"].get(name)
            if isinstance(existing, dict) and _pid_alive(
                int(existing.get("pid") or 0), existing.get("start_key")
            ):
                return False
            log = self.log_path(name)
            log_fh = open(log, "ab")
            child_env = dict(os.environ)
            if env:
                child_env.update({str(k): str(v) for k, v in env.items()})
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd_path),
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log_fh.close()
            start_key = _proc_start_key(proc.pid)
            data["workers"][name] = {
                "pid": proc.pid,
                "start_key": start_key,
                "argv": list(argv),
                "cwd": str(cwd_path),
                "log": str(log),
                "started_at": now_iso(),
                "meta": meta or {},
            }
            self._save(data)
            return True

    def kill(self, name: str, *, timeout: float = 3.0) -> bool:
        """SIGTERM the process group, then SIGKILL. Returns False if not found/alive."""
        with self._locked():
            data = self._load()
            entry = data["workers"].get(name)
            if not isinstance(entry, dict):
                return False
            pid = int(entry.get("pid") or 0)
            start_key = entry.get("start_key")
            if not _pid_alive(pid, start_key):
                data["workers"].pop(name, None)
                self._save(data)
                return False

        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not _pid_alive(pid, start_key):
                break
            time.sleep(0.1)
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

        with self._locked():
            data = self._load()
            data["workers"].pop(name, None)
            self._save(data)
        return True

    def active_workers(self) -> set[str]:
        """Challenge names for live hired workers named ``w-<challenge>``."""
        self.reap()
        out: set[str] = set()
        with self._locked():
            data = self._load()
            for name, entry in data["workers"].items():
                if not name.startswith("w-"):
                    continue
                if isinstance(entry, dict) and _pid_alive(
                    int(entry.get("pid") or 0), entry.get("start_key")
                ):
                    out.add(name[2:])
        return out

    def logs_tail(self, name: str, lines: int = 120) -> str:
        path = self.log_path(name)
        if not path.exists():
            with self._locked():
                entry = self._load()["workers"].get(name)
            if isinstance(entry, dict) and entry.get("log"):
                path = Path(entry["log"])
        if not path.exists():
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        parts = text.splitlines()
        return "\n".join(parts[-max(1, lines):])

    def status(self, *, reap: bool = True) -> list[dict]:
        """Snapshot of every registered worker, alive or dead.

        ``reap=True`` prunes dead entries first (mutating callers such as
        ``fleet``).  Read-only observers — the dashboard — pass ``reap=False``
        so a crashed worker is still reported with ``alive: False`` instead of
        vanishing, and so polling never mutates the registry.
        """
        if reap:
            self.reap()
        rows: list[dict] = []
        now = time.time()
        with self._locked():
            data = self._load()
            for name, entry in sorted(data["workers"].items()):
                if not isinstance(entry, dict):
                    continue
                pid = int(entry.get("pid") or 0)
                start_key = entry.get("start_key")
                alive = _pid_alive(pid, start_key)
                log = entry.get("log") or str(self.log_path(name))
                idle_s = None
                try:
                    mtime = Path(log).stat().st_mtime
                    idle_s = max(0, int(now - mtime))
                except OSError:
                    idle_s = None
                rows.append({
                    "name": name,
                    "alive": alive,
                    "pid": pid,
                    "started_at": entry.get("started_at"),
                    "idle_s": idle_s,
                    "log": log,
                    "meta": entry.get("meta") or {},
                })
        return rows

    def any_alive(self) -> bool:
        return any(r["alive"] for r in self.status())


def fleet_registry_root(base_dir: Path | str, root: str | None = None) -> Path:
    """Canonical registry location: ``<base>/<root>/`` (workers.json + logs/).

    ``root`` comes from ``fleet.json`` when a session wants a non-default
    layout; otherwise it is :func:`ben.core.paths.runtime_name`, so the
    registry can never be created at the base dir itself.
    """
    base = Path(base_dir).resolve()
    if root:
        return base / root
    return paths.registry_root(base)
