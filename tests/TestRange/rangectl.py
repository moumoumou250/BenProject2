#!/usr/bin/env python3
"""rangectl — start a vulnerable-lab range and prove you can reach it.

    python3 tests/TestRange/rangectl.py start spring-cve-2022-22947
    python3 tests/TestRange/rangectl.py connect spring-cve-2022-22947
    python3 tests/TestRange/rangectl.py down  spring-cve-2022-22947 --remove

`start` = resolve profile → deploy → health → **connect self-check** → hand over.
It stops there: no vulnerability proofs, no report, no ben run. The last thing it
prints is a ready-to-paste handoff for the operator's main flow.

Exit codes: 0 = started and connected, 1 = a stage failed, 2 = usage/config.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from trange import connect, dockerops, ports  # noqa: E402
from trange.profiles import Profile, ProfileError, discover_profiles, load_profile  # noqa: E402
from trange.runner import (RangeRun, default_out_dir, environment_fingerprint,  # noqa: E402
                           run_range)

PROFILES = HERE / "profiles"


def _log(message: str) -> None:
    print(f"[trange] {message}", flush=True)


def _profile_dir(args) -> Path:
    return Path(args.profiles) if getattr(args, "profiles", None) else PROFILES


def _profiles(args) -> dict[str, Profile]:
    return discover_profiles(_profile_dir(args))


def _one(args) -> Profile:
    ref = str(args.id)
    path = Path(ref) if ref.endswith((".toml", ".json")) else _profile_dir(args) / f"{ref}.toml"
    if path.exists():
        return load_profile(path)
    # an id does not have to match its file name — look it up by `id` too
    found = _profiles(args).get(ref)
    if found is not None:
        return found
    available = ", ".join(sorted(_profiles(args))) or "none"
    raise ProfileError(f"no profile for {ref!r} (looked for {path}; available: {available})")


def _new_run(profile: Profile, out: str | None) -> RangeRun:
    directory = Path(out) if out else default_out_dir(profile)
    directory.mkdir(parents=True, exist_ok=True)
    return RangeRun(profile=profile, started=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    out_dir=directory)


# --------------------------------------------------------------------------
# port bookkeeping: a busy port must not stop a start
# --------------------------------------------------------------------------
def relocate_if_busy(profile: Profile, *, want_port: int | None = None) -> tuple[Profile, str]:
    """Move the range onto a free host port when the declared one is taken."""
    if profile.compose_dir:
        # compose owns its port list; rewriting the profile would lie about it
        return profile, "compose-managed range: ports come from the compose file"

    if want_port is not None:
        current = next((p for p in (ports.host_port(m) for m in profile.ports)
                        if p is not None), None)
        if current is None:
            return profile, f"--port {want_port} ignored (profile declares no host ports)"
        if not ports.is_free(want_port):
            raise ProfileError(f"requested port {want_port} is already in use")
        return ports.relocate(profile, current, want_port), f"host port {current} -> {want_port}"

    ours: set[int] = set()
    if profile.container:
        state = dockerops.inspect(profile.container)
        # Only a *running* container legitimately holds its published ports.
        # A stopped one holds nothing, so a busy port belongs to someone else.
        if state.running:
            for entry in state.ports or []:
                left = entry.split("->")[0]
                if ":" in left and left.rsplit(":", 1)[1].isdigit():
                    ours.add(int(left.rsplit(":", 1)[1]))
    busy = ports.conflicts(profile, ours=ours)
    if not busy:
        return profile, ""
    new_port = ports.pick_free(busy[0] + 1)
    return (ports.relocate(profile, busy[0], new_port),
            f"host port {busy[0]} busy -> moved to {new_port}")


def adapt_stopped_container(profile: Profile) -> tuple[Profile, str]:
    """A stopped container keeps its old port wiring; re-creating is the only fix.

    Docker cannot change a stopped container's published ports. When the
    profile has been moved to a free port, the honest move is to leave the
    original as a template and create a sibling from the same image.
    """
    if not profile.container or not profile.image:
        return profile, ""
    state = dockerops.inspect(profile.container)
    if not state.exists or state.running:
        return profile, ""

    def host_ports(entries: list[str]) -> set[str]:
        out = set()
        for entry in entries:
            left = entry.split("->")[0]
            if ":" in left:
                out.add(left.rsplit(":", 1)[1])
        return out

    wanted = {str(ports.host_port(m)) for m in profile.ports if ports.host_port(m) is not None}
    actual = host_ports(state.ports or [])
    if not wanted or not actual or wanted == actual:
        return profile, ""

    clone = copy.deepcopy(profile)
    base = re.sub(r"-\d+$", "", profile.container)
    primary = sorted(wanted)[0]
    clone.deploy["container"] = f"{base}-{primary}"
    return clone, (f"stopped container {profile.container} is wired to "
                   f"{sorted(actual)} -> creating {clone.container} on {sorted(wanted)}")


# --------------------------------------------------------------------------
# output helpers
# --------------------------------------------------------------------------
def _print_steps(run: RangeRun) -> None:
    print()
    for step in run.steps:
        print(f"  [{'PASS' if step.ok else 'FAIL'}] {step.name:8s} {step.detail}")


def _print_handoff(run: RangeRun) -> None:
    """The tool's last job: hand a ready-to-paste next step to the main flow."""
    env = run.out_dir / "connect.env"
    print()
    print("handoff (nothing below is run by rangectl):")
    print(f"  source {env}")
    print(f'  ben setup --goal "{run.profile.handoff_goal()}" --agents')
    print("  ben command            # or: ben auto")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_list(args) -> int:
    profiles = _profiles(args)
    if not profiles:
        print(f"no profiles in {_profile_dir(args)}")
        return 0
    rows = []
    for pid, prof in profiles.items():
        state = dockerops.inspect(prof.container) if prof.container else None
        if state and state.running:
            status = f"up ({state.status})"
        elif state and state.exists:
            status = f"stopped ({state.status})"
        elif prof.container:
            status = "absent"
        else:
            status = "external"
        rows.append({"id": pid, "cve": prof.cve or "-", "status": status, "target": prof.url})
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    width = max(len(r["id"]) for r in rows)
    print(f"{'id'.ljust(width)}  {'cve'.ljust(14)} {'status'.ljust(22)} target")
    for r in rows:
        print(f"{r['id'].ljust(width)}  {r['cve'].ljust(14)} {r['status'].ljust(22)} {r['target']}")
    return 0


def cmd_show(args) -> int:
    prof = _one(args)
    print(f"id:        {prof.id}\ntitle:     {prof.title}\ncve:       {prof.cve or '-'}")
    print(f"profile:   {prof.path}")
    print(f"container: {prof.container or '-'}  image={prof.image or '-'}")
    if prof.compose_dir:
        print(f"compose:   {prof.compose_dir}")
    print(f"ports:     {prof.ports or '-'}")
    print(f"target:    {prof.url}")
    print(f"health:    {prof.health_url()}  expect={prof.health.get('expect_status', 200)} "
          f"budget={prof.boot_timeout:.0f}s")
    return 0


def cmd_start(args) -> int:
    """Start the range, prove the link, print the handoff."""
    profile = _one(args)
    profile, moved = relocate_if_busy(profile, want_port=args.port)
    if moved:
        _log(moved)
    profile, adapted = adapt_stopped_container(profile)
    if adapted:
        _log(adapted)

    out_dir = Path(args.out) if args.out else default_out_dir(profile)
    _log(f"target {profile.id} -> {profile.url}")

    run = run_range(profile, deploy=not args.no_deploy, out_dir=out_dir, log=_log)
    conn = run.connection

    if args.json:
        print(json.dumps({"ok": run.ok, "profile": str(profile.path),
                          "connection": conn,
                          "steps": [{"name": s.name, "ok": s.ok, "detail": s.detail}
                                    for s in run.steps]}, indent=2))
    else:
        failed = next((s for s in run.steps if not s.ok), None)
        summary = conn.get("summary") or (
            f"{failed.name} failed — {failed.detail}" if failed else "not connected")
        print()
        print(("ok: " if run.ok else "FAIL: ") + summary)
        _print_steps(run)
        if conn.get("ok"):
            print(f"\nenv:  {run.out_dir / 'connect.env'}")
            _print_handoff(run)
    return 0 if run.ok else 1


def cmd_connect(args) -> int:
    """Connection self-check only: is the range reachable from here, right now?"""
    prof = _one(args)
    run = _new_run(prof, args.out)
    conn = connect.check(prof, log=_log)
    env_path = connect.write_env(conn, run.out_dir)
    if args.json:
        print(json.dumps(conn.as_dict(), indent=2))
    else:
        print(("ok: " if conn.ok else "FAIL: ") + conn.summary)
        print(f"env:  {env_path}")
        for line in conn.env_lines():
            print(f"  {line}")
        if conn.container_ip:
            inner = conn.container_port or conn.port
            print(f"  # from another container: http://{conn.container_ip}:{inner}")
    return 0 if conn.ok else 1


def cmd_down(args) -> int:
    prof = _one(args)
    if not prof.container:
        print("profile declares no container — nothing to stop")
        return 0
    ok, detail = dockerops.stop(prof.container)
    print(("stopped: " if ok else "FAIL: ") + (detail or prof.container))
    if args.remove:
        ok2, detail2 = dockerops.remove(prof.container)
        print(("removed: " if ok2 else "remove failed: ") + detail2)
    return 0 if ok else 1


def cmd_doctor(args) -> int:
    print("environment fingerprint:")
    for key, value in environment_fingerprint().items():
        print(f"  {key:8s} {value}")
    print(f"  profiles {_profile_dir(args)}")
    missing = []
    try:
        dockerops.docker_bin()
    except dockerops.DockerUnavailable as exc:
        missing.append(str(exc))
    if sys.version_info < (3, 11):
        missing.append("Python 3.11+ recommended for TOML profiles (JSON still works)")
    for item in missing:
        print(f"  WARN {item}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rangectl", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profiles", help=f"profile directory (default: {PROFILES})")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start", help="start the range, prove the connection, print the handoff")
    p.add_argument("id", help="profile id (or a path to a .toml/.json profile)")
    p.add_argument("--port", type=int, help="force this host port")
    p.add_argument("--no-deploy", action="store_true", help="range is managed elsewhere")
    p.add_argument("--out", help="artifact directory")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("connect", help="connection self-check only + connect.env")
    p.add_argument("id")
    p.add_argument("--out", help="artifact directory")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_connect)

    p = sub.add_parser("down", help="stop (and optionally remove) the range")
    p.add_argument("id")
    p.add_argument("--remove", action="store_true", help="docker rm -f afterwards")
    p.set_defaults(func=cmd_down)

    p = sub.add_parser("list", help="list profiles with live container status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="print a resolved profile")
    p.add_argument("id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("doctor", help="check docker / python / runtime paths")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ProfileError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        return 2
    except ports.PortUnavailable as exc:
        print(f"port error: {exc}", file=sys.stderr)
        return 2
    except dockerops.DockerUnavailable as exc:
        print(f"docker unavailable: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
