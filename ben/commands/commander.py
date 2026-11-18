"""Commander board reading and worker hire/fire."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from ben.commands.util import _resolve_templates_dir
from ben.core.timebudget import deadline_from_args, format_time_budget
from ben.commands.fleet import (
    FLEET_FILE, _active_workers, _fire_worker, _hire_worker, _fleet_load,
    _ben_engine_prefix,
)
from ben.agents.factory import _load_template
from ben.core import paths
from ben.core.errors import FGError
from ben.core.graph import build_graph_view
from ben.core.store import Store
from ben.llm.jsonx import extract_json_object
from ben.llm.runner import run_claude
from ben.agents.prompt import _replace_placeholders


def _board_summary(root: Path) -> list[dict]:
    """One-line status per challenge graph under root, for the commander."""
    rows = []
    for store_dir in sorted(p for p in root.glob("*/.ben") if (p / "project.json").exists()):
        try:
            store = Store(store_dir)
            g = build_graph_view(store)
        except FGError:
            continue
        kinds: dict[str, int] = {}
        flags_submitted = flags_recorded = 0
        last_activity = ""
        for f in g["facts"]:
            k = f.get("kind")
            if k:
                kinds[k] = kinds.get(k, 0) + 1
            if k == "flag":
                status = (f.get("data") or {}).get("status", "recorded")
                if status == "submitted":
                    flags_submitted += 1
                else:
                    flags_recorded += 1
            if f.get("created_at", "") > last_activity:
                last_activity = f["created_at"]
        rows.append({
            "name": store_dir.parent.name,
            "status": g["project"]["status"],
            "goal": (g["project"]["goal"] or "")[:80],
            "flags_submitted": flags_submitted,
            "flags_recorded": flags_recorded,
            "kinds": " ".join(f"{v} {k}" for k, v in sorted(kinds.items())) or "-",
            "open_intents": len(g["open_intents"]),
            "last_activity": last_activity or "-",
        })
    return rows


def render_board(rows: list[dict]) -> str:
    has_worker = any("worker" in r for r in rows)
    head = "challenge | status | flags(sub/rec) | intel | open | last activity"
    if has_worker:
        head += " | worker"
    lines = [head + " | goal"]
    for r in rows:
        line = (
            f"{r['name']} | {r['status']} | {r['flags_submitted']}/{r['flags_recorded']} "
            f"| {r['kinds']} | {r['open_intents']} | {r['last_activity']}"
        )
        if has_worker:
            line += f" | {r.get('worker', '-')}"
        lines.append(line + f" | {r['goal']}")
    lines.append(
        "note: flags(sub/rec) = submitted/recorded-but-not-submitted; "
        "intel = counts by kind (host service cred vuln loot flag); "
        "worker=yes means a hired worker process (w-<name>) is already on it."
    )
    return "\n".join(lines)


def _parse_command_payload(payload: dict) -> tuple[str, str, int, str]:
    """Return (action, target, minutes, note). action in work|hire|fire|stop|reject."""
    if payload.get("accepted") is False:
        return "reject", "", 0, str(payload.get("reason", ""))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise FGError(f"invalid command payload: {payload}")
    action = data.get("action")
    if action not in ("work", "hire", "fire", "stop"):
        raise FGError(f"command payload action must be work|hire|fire|stop, got {action!r}")
    if action == "stop":
        return "stop", "", 0, str(data.get("reason", ""))
    target = data.get("target")
    if not isinstance(target, str) or not target.strip():
        raise FGError(f"command payload {action} needs a 'target' challenge name")
    minutes = 0
    if action in ("work", "hire"):
        minutes = data.get("minutes", 20)
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes < 1:
            raise FGError("command payload 'minutes' must be a positive number")
        minutes = int(minutes)
    note = str(data.get("note", ""))[:300]
    return action, target.strip(), minutes, note


def _command_fleet_cfg(args) -> dict:
    """Fleet context for the commander: fleet.json in cwd if present, else
    sane defaults so hire/fire work even without a fleet config."""
    path = Path(args.fleet_file) if getattr(args, "fleet_file", None) else Path(FLEET_FILE)
    if path.exists():
        try:
            cfg = _fleet_load(path)
        except FGError:
            cfg = {}
    else:
        cfg = {}
    cfg.setdefault("session", "ben-fleet")
    cfg.setdefault("root", args.root)
    return cfg


def cmd_command(args) -> int:
    """Field-commander loop: read the board, ask the model where the next
    time slice goes, run `ben auto` there, repeat until deadline/stop.

    Decisions: work (blocking slice here), hire (spawn a parallel worker
    process on a challenge), fire (stop a worker), stop."""
    root = Path(args.root)
    if not root.is_dir():
        raise FGError(f"command root {root} is not a directory")
    if not list(root.glob("*/.ben/project.json")):
        raise FGError(f"no */.ben/project.json found under {root}")
    deadline = deadline_from_args(args)
    if deadline is None:
        raise FGError("command needs --minutes or --deadline (the match slot clock)")
    templates_dir = _resolve_templates_dir(args)
    model = args.model
    timeout = args.timeout
    skip = args.skip_permissions
    cli = [sys.executable, str(Path(__file__).resolve())]
    passthrough = ["--model", model]
    if skip:
        passthrough.append("--skip-permissions")
    if args.verify:
        passthrough.append("--verify")
    if args.templates:
        passthrough.extend(["--templates", args.templates])

    fleet_cfg = _command_fleet_cfg(args)
    fleet_cfg["_base_dir"] = str(Path.cwd())
    session = fleet_cfg["session"]
    fleet_root = fleet_cfg.get("root", paths.runtime_name())
    base_dir = Path(fleet_cfg["_base_dir"])

    print(f"[command] field commander over {root}  "
          f"deadline {datetime.fromtimestamp(deadline).strftime('%H:%M')}")
    print(f"[command] fleet session {session!r} (hire/fire via worker processes w-*)")
    tpl = _load_template(templates_dir, "command.md")
    noop_streak = 0
    worked: dict[str, int] = {}
    while time.time() < deadline:
        workers = _active_workers(base_dir, fleet_root)
        rows = [r for r in _board_summary(root) if r["status"] != "completed"]
        for r in rows:
            r["worker"] = "yes" if r["name"] in workers else "-"
        if not rows and not workers:
            print("[command] all challenge graphs completed")
            break
        if not rows:
            # everything done except workers still burning — wait on them
            print(f"[command] waiting on hired workers: {sorted(workers)}")
            time.sleep(args.poll_seconds)
            continue
        remaining_min = max(1, int((deadline - time.time()) // 60))
        action = target = ""
        minutes = min(args.minutes_default, remaining_min)
        note = ""
        try:
            prompt = _replace_placeholders(tpl, {
                "board": render_board(rows),
                "time_budget": format_time_budget(deadline),
            })
            envelope = run_claude(
                prompt, model=model, timeout=timeout, skip_permissions=False,
                append_system=None, cwd=Path.cwd(),
            )
            action, target, minutes_raw, note = _parse_command_payload(
                extract_json_object(envelope.get("result", ""))
            )
            minutes = max(1, min(int(minutes_raw or minutes), args.minutes_max, remaining_min))
        except FGError as exc:
            print(f"[command] model decision failed ({exc}); falling back to round-robin")
            free = [r for r in rows if r["name"] not in workers]
            row = next((r for r in free if worked.get(r["name"], 0) == min(worked.values() or [0])), rows[0])
            action, target, minutes = "work", row["name"], min(args.minutes_default, remaining_min)
            note = "round-robin fallback"
        if action == "reject":
            noop_streak += 1
            if noop_streak >= 2:
                print("[command] model rejected the board twice — stopping")
                break
            continue
        if action == "stop":
            print(f"[command] model says stop: {note}")
            break
        names = {r["name"] for r in rows}
        if target not in names:
            print(f"[command] unknown/parked target {target!r}; skipping decision")
            noop_streak += 1
            if noop_streak >= 3:
                break
            continue
        noop_streak = 0
        worked[target] = worked.get(target, 0) + minutes
        if action == "hire":
            spawned = _hire_worker(fleet_cfg, target, minutes,
                                   max_steps=args.max_steps,
                                   extra=" ".join(passthrough[1:]))
            tag = "hired" if spawned else "already has a worker"
            print(f"[command] hire {target} for {minutes}m -> {tag} ({note})")
            time.sleep(args.poll_seconds)
            continue
        if action == "fire":
            killed = _fire_worker(base_dir, target, fleet_root=fleet_root)
            print(f"[command] fire {target} -> {'released' if killed else 'no worker'} ({note})")
            time.sleep(args.poll_seconds)
            continue
        print(f"\n[command] -> {target} for {minutes}m ({note}) "
              f"[{format_time_budget(deadline)}]")
        cmd = cli + [
            "--store", str(root / target / ".ben"), "auto",
            "--minutes", str(minutes), "--max-steps", str(args.max_steps),
        ] + passthrough
        subprocess.run(cmd, cwd=str(root / target), check=False)

    print("[command] final board:")
    for r in _board_summary(root):
        mark = "DONE" if r["status"] == "completed" else r["status"]
        print(f"[command]   {r['name']}: {mark}  flags={r['flags_submitted']}/{r['flags_recorded']}")
    return 0
