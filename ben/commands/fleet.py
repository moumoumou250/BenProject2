"""Process fleet management (worker process registry)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ben.core import paths
from ben.core.errors import FGError
from ben.core.io import read_json
from ben.runtime.agents import AgentRegistry, fleet_registry_root


def _fleet_load(path: Path) -> dict:
    if not path.exists():
        raise FGError(f"no fleet config at {path}; run `ben fleet init` first")
    cfg = read_json(path)
    if not isinstance(cfg, dict) or not isinstance(cfg.get("session"), str):
        raise FGError(f"fleet config {path} needs a string 'session'")
    panes = cfg.get("panes")
    if not isinstance(panes, list) or not panes:
        raise FGError(f"fleet config {path} needs a non-empty 'panes' list")
    return cfg


def _ben_engine_prefix() -> str:
    """Absolute, PATH-independent way to invoke this CLI in generated commands."""
    launcher = Path(__file__).resolve().parents[2] / "bin" / "ben"
    return f"python3 {launcher}"


def _fleet_pane_command(cfg: dict, pane: dict, base_dir: Path | None = None) -> str:
    ptype = pane.get("type", "shell")
    root = cfg.get("root", paths.runtime_name())
    deadline = cfg.get("deadline")
    engine = _ben_engine_prefix()
    if ptype == "command":
        cmd = f"{engine} command --root {root}"
        if deadline:
            cmd += f" --deadline {deadline}"
        extra = pane.get("extra_args", "")
        cmd += f" {extra}" if extra else ""
    elif ptype.startswith("auto:"):
        name = ptype.split(":", 1)[1]
        cmd = f"{engine} --store {root}/{name}/.ben auto"
        if deadline:
            cmd += f" --deadline {deadline}"
        extra = pane.get("extra_args", "")
        cmd += f" {extra}" if extra else ""
    elif ptype == "shell":
        command = pane.get("command")
        if not isinstance(command, str) or not command.strip():
            raise FGError("shell pane needs a 'command'")
        return command
    else:
        raise FGError(f"unknown fleet pane type {ptype!r}")
    if base_dir is not None:
        cmd = f"cd {base_dir} && {cmd}"
    return cmd


def _registry_for(cfg: dict, base_dir: Path | None = None) -> AgentRegistry:
    base = Path(base_dir or cfg.get("_base_dir") or Path.cwd()).resolve()
    root = cfg.get("root", paths.runtime_name())
    return AgentRegistry(fleet_registry_root(base, root))


def cmd_fleet(args) -> int:
    path = Path(args.file)
    if args.action == "init":
        if path.exists():
            raise FGError(f"fleet config already exists: {path}")
        path.write_text(json.dumps(FLEET_TEMPLATE, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print(f"wrote {path} — edit deadline/panes, then `ben fleet up`")
        return 0
    if args.action == "up":
        cfg = _fleet_load(path)
        session = cfg["session"]
        base_dir = path.resolve().parent
        cfg["_base_dir"] = str(base_dir)
        registry = _registry_for(cfg, base_dir)
        if registry.any_alive():
            raise FGError(
                f"fleet {session!r} already exists; `ben fleet down` first"
            )
        for pane in cfg["panes"]:
            name = str(pane.get("name") or pane.get("type"))
            command = _fleet_pane_command(cfg, pane, base_dir=base_dir)
            ok = registry.spawn(
                name,
                ["bash", "-lc", command],
                cwd=base_dir,
                env={**os.environ, "BEN_WORKER": name},
                meta={"session": session, "pane": pane},
            )
            print(f"[fleet] {name}: {command}" + ("" if ok else " (already running)"))
        print(
            f"[fleet] session {session!r} up — tail logs under "
            f"{registry.logs_dir}/. `ben fleet down` to stop."
        )
        return 0
    if args.action == "down":
        cfg = _fleet_load(path)
        session = cfg["session"]
        base_dir = path.resolve().parent
        cfg["_base_dir"] = str(base_dir)
        registry = _registry_for(cfg, base_dir)
        rows = registry.status()
        if not any(r["alive"] for r in rows):
            print(f"[fleet] session {session!r} not running")
            return 0
        for row in rows:
            registry.kill(row["name"])
        print(f"[fleet] session {session!r} killed")
        return 0
    if args.action == "hire":
        cfg = _fleet_load(path) if path.exists() else {"session": "ben-fleet", "root": paths.runtime_name()}
        cfg["_base_dir"] = str(Path.cwd())
        if not args.target:
            raise FGError("fleet hire needs --target <challenge>")
        minutes = args.minutes or 30
        spawned = _hire_worker(cfg, args.target, minutes, max_steps=args.max_steps or 8,
                               extra=args.extra_args or "")
        print(f"[fleet] hire {args.target}: "
              f"{'worker window w-%s up' % args.target if spawned else 'worker already running'}")
        return 0
    if args.action == "fire":
        cfg = _fleet_load(path) if path.exists() else {"session": "ben-fleet", "root": paths.runtime_name()}
        cfg["_base_dir"] = str(Path.cwd())
        if not args.target:
            raise FGError("fleet fire needs --target <challenge>")
        root = Path(cfg.get("_base_dir", ".")).resolve()
        killed = _fire_worker(root, args.target, fleet_root=cfg.get("root", paths.runtime_name()))
        print(f"[fleet] fire {args.target}: {'released' if killed else 'no worker running'}")
        return 0
    if args.action == "workers":
        cfg = _fleet_load(path) if path.exists() else {"session": "ben-fleet", "root": paths.runtime_name()}
        cfg["_base_dir"] = str(Path.cwd())
        workers = sorted(_active_workers(Path(cfg["_base_dir"]), cfg.get("root", paths.runtime_name())))
        print("hired workers: " + (", ".join(workers) if workers else "(none)"))
        return 0
    if args.action == "status":
        cfg = _fleet_load(path)
        session = cfg["session"]
        base_dir = path.resolve().parent
        cfg["_base_dir"] = str(base_dir)
        registry = _registry_for(cfg, base_dir)
        rows = registry.status()
        print(f"fleet {session!r} (proc runtime):")
        if not rows:
            print("  (no workers)")
            return 0
        for r in rows:
            alive = "alive" if r["alive"] else "dead"
            idle = f" idle={r['idle_s']}s" if r["idle_s"] is not None else ""
            print(f"  {r['name']:<16} {alive} pid={r['pid']}{idle} log={r['log']}")
        return 0
    raise FGError(f"unknown fleet action {args.action!r}")


def _active_workers(root: Path | str, fleet_root: str | None = None) -> set[str]:
    """Challenge names with a live hired worker process (w-<name>)."""
    return AgentRegistry(fleet_registry_root(root, fleet_root)).active_workers()


def _hire_worker(cfg: dict, target: str, minutes: int, max_steps: int = 8,
                 extra: str = "") -> bool:
    """Spawn (or reuse) a worker process w-<target> running `auto`.
    Returns False if a worker is already running for that target."""
    root = cfg.get("root", paths.runtime_name())
    base = Path(cfg.get("_base_dir", ".")).resolve()
    registry = AgentRegistry(fleet_registry_root(base, root))
    window = f"w-{target}"
    if target in registry.active_workers():
        return False
    engine = _ben_engine_prefix()
    command = (
        f"cd {base} && {engine} --store {root}/{target}/.ben auto "
        f"--minutes {minutes} --max-steps {max_steps}{(' ' + extra) if extra else ''}"
    )
    return registry.spawn(
        window,
        ["bash", "-lc", command],
        cwd=base,
        env={**os.environ, "BEN_WORKER": window},
        meta={"target": target, "minutes": minutes, "session": cfg.get("session")},
    )


def _fire_worker(root: Path | str, target: str, *, fleet_root: str | None = None) -> bool:
    """Kill the hired worker process for a target. Returns False if none."""
    registry = AgentRegistry(fleet_registry_root(root, fleet_root))
    window = f"w-{target}"
    if target not in registry.active_workers():
        return False
    return registry.kill(window)


FLEET_FILE = "fleet.json"


FLEET_TEMPLATE = {
    "session": "ben-fleet",
    "root": paths.runtime_name(),
    "deadline": "2026-10-17T13:00:00",
    "panes": [
        {"name": "commander", "type": "command", "extra_args": "--verify"},
        {"name": "board", "type": "shell", "command": "watch -n 30 'ben sweep-status --root runs 2>/dev/null || ls runs'"},
    ],
    "_comment": (
        "types: command (ben command --root ROOT --deadline D), "
        "auto:<name> (ben auto in runs/<name>), shell (any command). "
        "`ben fleet up` starts the process fleet; "
        "`down` kills it. Run `up` inside the match debugging window; the "
        "loops keep running unattended once the match starts."
    ),
}
