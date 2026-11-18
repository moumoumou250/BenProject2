"""Live status aggregation for the web dashboard.

One call collects everything the dashboard shows: project meta, per-kind
fact counters, the task list (with briefs), recent findings, the worker
fleet, and log tails.  All data sources already exist — this module only
reads them; it never mutates the graph or the registry.

Graph reads happen under ``store.locked()`` like every other read path;
registry reads use the registry's own file lock, so they must stay OUTSIDE
the store lock (never nest the two).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

from ben.core import paths
from ben.core.store import Store

# a worker id looks like "<model>-<pid>" (ben.agents.factory._worker_id)
_WORKER_ID_RE = re.compile(r"^(?P<model>.+)-(?P<pid>\d+)$")

_LOG_TAIL_LINES = 6
_RECENT_FACTS = 10


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def find_registry_root(store: Store) -> Path | None:
    """Locate the fleet registry (a dir holding workers.json) near the store.

    Layout: the graph lives at ``<base>/<root>/<name>/.ben`` and the registry
    at ``<base>/<root>/`` (see runtime.agents.fleet_registry_root).  Walk the
    store's ancestors first, then the cwd defaults.
    """
    candidates: list[Path] = []
    p = store.root.resolve()
    for parent in list(p.parents)[:6]:
        candidates.append(parent / "workers.json")
    cwd = Path.cwd()
    candidates.append(paths.output_dir(cwd) / "workers.json")
    candidates.append(cwd / "workers.json")
    for cand in candidates:
        try:
            if cand.exists():
                return cand.parent
        except OSError:
            continue
    return None


def _task_view(i: dict) -> dict:
    return {
        "id": i.get("id"),
        "title": i.get("title"),
        "description": i.get("description"),
        "doc": i.get("doc"),
        "status": i.get("status"),
        "worker": i.get("worker"),
        "from": i.get("from") or [],
        "to": i.get("to"),
        "requires_confirmation": bool(i.get("requires_confirmation")),
        "confirmed_at": i.get("confirmed_at"),
        "created_at": i.get("created_at"),
        "concluded_at": i.get("concluded_at"),
    }


def _fact_view(f: dict) -> dict:
    return {
        "id": f.get("id"),
        "title": f.get("title"),
        "description": f.get("description"),
        "kind": f.get("kind"),
        "data": f.get("data"),
        "doc": f.get("doc"),
        "created_at": f.get("created_at"),
        "creator": f.get("creator"),
        "source_intent": f.get("source_intent"),
    }


def _intent_matches_worker(intent: dict, pid: int, name: str) -> bool:
    """Best-effort: does this claimed intent belong to the fleet worker?

    Worker ids embed the pid of the `ben auto` process, which is exactly the
    process the registry tracks — so a numeric-suffix match is reliable when
    it fires; a miss just means "unknown task", never a wrong one.
    """
    w = str(intent.get("worker") or "")
    m = _WORKER_ID_RE.match(w)
    if m and int(m.group("pid")) == pid:
        return True
    return w == name


def _fleet_view(registry) -> list[dict]:
    # reap=False: the dashboard must be a pure reader — a poll every 2s cannot
    # delete registry entries — and a crashed worker has to stay visible as a
    # dead card (README §3 "worker 崩溃"), not silently disappear.
    rows = registry.status(reap=False)
    out: list[dict] = []
    for r in rows:
        pid = int(r.get("pid") or 0)
        meta = r.get("meta") or {}
        minutes = meta.get("minutes")
        timebox_s = int(float(minutes) * 60) if isinstance(minutes, (int, float)) and minutes > 0 else None
        started = _parse_iso(r.get("started_at"))
        uptime_s = int((_now_utc() - started).total_seconds()) if started else None
        timebox_left_s = None
        if timebox_s is not None and uptime_s is not None:
            timebox_left_s = timebox_s - uptime_s
        tail = registry.logs_tail(r["name"], _LOG_TAIL_LINES)
        lines = tail.splitlines()[-_LOG_TAIL_LINES:] if tail else []
        last_line = lines[-1] if lines else ""
        out.append({
            "name": r["name"],
            "alive": bool(r.get("alive")),
            "pid": pid,
            "started_at": r.get("started_at"),
            "uptime_s": uptime_s,
            "idle_s": r.get("idle_s"),
            "timebox_s": timebox_s,
            "timebox_left_s": timebox_left_s,
            "meta": meta,
            "last_line": last_line,
        })
    return out


def build_status_view(store: Store, registry_root: Path | None = None) -> dict:
    """Materialize the whole dashboard payload as plain JSON-safe dict."""
    with store.locked():
        project = store.load_project()
        facts = store.list_facts()
        intents = store.list_intents()

    kind_counts: dict[str, int] = {}
    for f in facts:
        k = f.get("kind") or "untyped"
        kind_counts[k] = kind_counts.get(k, 0) + 1

    open_intents = [i for i in intents if i.get("to") is None]
    done_intents = [i for i in intents if i.get("to") is not None]
    claimed = [i for i in open_intents if i.get("status") == "claimed"]

    def _rank(i: dict) -> int:
        if i.get("to") is not None:
            return 4  # done last
        if i.get("status") == "claimed":
            return 0  # in flight first
        return 1

    tasks = sorted(intents, key=lambda i: (_rank(i), i.get("created_at") or ""))

    recent_facts = sorted(
        (f for f in facts if f.get("id") != "goal"),
        key=lambda f: f.get("created_at") or "",
        reverse=True,
    )[:_RECENT_FACTS]

    started = _parse_iso(project.get("created_at"))
    elapsed_s = int((_now_utc() - started).total_seconds()) if started else None

    out: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project": {
            "goal": project.get("goal"),
            "status": project.get("status"),
            "created_at": project.get("created_at"),
        },
        "elapsed_s": elapsed_s,
        "summary": {
            "facts": len(facts),
            "intents": len(intents),
            "tasks_done": len(done_intents),
            "tasks_open": len(open_intents),
            "tasks_claimed": len(claimed),
            "kind_counts": kind_counts,
        },
        "tasks": [_task_view(i) for i in tasks],
        "recent_facts": [_fact_view(f) for f in recent_facts],
        "workers": [],
        "log_tail": {},
        "registry_found": False,
    }

    # fleet part: registry reads use their own lock — outside store.locked()
    root = registry_root if registry_root is not None else find_registry_root(store)
    if root is not None:
        try:
            from ben.runtime.agents import AgentRegistry

            registry = AgentRegistry(Path(root))
            workers = _fleet_view(registry)
            out["workers"] = workers
            out["registry_found"] = True
            # link claimed intents to workers via the embedded pid
            now = _now_utc()
            for w in workers:
                cur = []
                for i in claimed:
                    if not w["pid"] or not _intent_matches_worker(i, w["pid"], w["name"]):
                        continue
                    created = _parse_iso(i.get("created_at"))
                    age_s = int((now - created).total_seconds()) if created else None
                    cur.append({
                        "id": i.get("id"),
                        "title": i.get("title") or i.get("description"),
                        "age_s": age_s,
                    })
                w["current"] = cur
            for w in workers:
                tail = registry.logs_tail(w["name"], _LOG_TAIL_LINES)
                out["log_tail"][w["name"]] = tail.splitlines()[-_LOG_TAIL_LINES:] if tail else []
        except Exception:
            # a missing/corrupt registry must never break the dashboard
            pass
    return out
