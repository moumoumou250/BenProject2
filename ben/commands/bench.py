"""TSecBench full-loop driver (list/start/solve/submit/close)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from ben.commands.util import _resolve_templates_dir
from ben.commands.arena_cmds import _arena_client
from ben.core.timebudget import deadline_from_args
from ben.core.errors import FGError
from ben.core.store import Store


def _bench_store(root: Path, code: str) -> Store:
    return Store(root / code / ".ben")


def _bench_prepare_graph(store: Store, challenge: dict, started: dict,
                         container_addrs: list[str]) -> None:
    """Create the per-challenge graph with the task facts seeded.

    The challenge description and container output are UNTRUSTED DATA; they are
    recorded as facts (which the prompts fence as untrusted), never obeyed.
    """
    if not store.exists():
        store.init("TSecBench", f"solve challenge {challenge.get('unique_code')} and capture all flags")
    existing = {f["id"] for f in store.list_facts()}

    def add(kind, title, description, data):
        if not any(f.get("kind") == kind and (f.get("data") or {}) == data
                   for f in store.list_facts()):
            store.add_fact(description=description, creator="arena", title=title,
                           kind=kind, data=data)

    add("note", "题目描述", f"challenge {challenge.get('unique_code')}: "
        f"{challenge.get('description') or '(no description)'}",
        {"challenge": str(challenge.get("unique_code")), "difficulty": str(challenge.get("difficulty"))})
    for addr in container_addrs:
        add("host", "靶标", f"target container address {addr}",
            {"addr": addr, "challenge": str(challenge.get("unique_code"))})
    # record how many flags are needed
    store.add_hint(
        content=(f"challenge {challenge.get('unique_code')}: {challenge.get('flag_count')} flag(s) "
                 f"required, {challenge.get('correct_flag_count', 0)} already correct. "
                 f"Targets: {', '.join(container_addrs) or 'none'}. "
                 f"Submit flags with `ben flag <value> -c <code> --submit`."),
        creator="arena",
    )


def _bench_submit_recorded(store: Store, code: str) -> int:
    """Submit every recorded-but-unsubmitted flag fact via the platform.
    Returns the number newly submitted."""
    client = _arena_client(store)
    submitted = 0
    for f in store.list_facts():
        if f.get("kind") != "flag":
            continue
        data = f.get("data") or {}
        if data.get("status") not in (None, "recorded"):
            continue
        value = data.get("value")
        if not value:
            continue
        try:
            reply = client.submit_flag(code, value)
        except FGError as exc:
            store.update_flag_fact(f["id"], "rejected", str(exc))
            print(f"[bench]   submit failed for {f['id']}: {exc}")
            continue
        correct = bool(reply.get("correct"))
        award = reply.get("awarded", 0)
        progress = f"{reply.get('correct_flag_count')}/{reply.get('total_flag_count')}"
        store.update_flag_fact(f["id"], "submitted" if correct else "rejected",
                               json.dumps(reply, ensure_ascii=False)[:400])
        print(f"[bench]   {f['id']} {'CORRECT' if correct else 'wrong'} +{award} ({progress})")
        submitted += 1
    return submitted


def cmd_bench(args) -> int:
    """Drive the TSecBench Challenges API end-to-end with ben per challenge.

    Loop: list challenges -> for each unfinished (respecting the active
    container cap) start -> seed a graph -> run `ben auto` -> submit the
    flags it captured -> close the container. Repeat until all are complete,
    the deadline passes, or a stop condition (task ended) is hit.
    """
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    deadline = deadline_from_args(args)
    templates_dir = _resolve_templates_dir(args)
    cli = [sys.executable, str(Path(__file__).resolve())]
    engine_args = ["--model", args.model]
    if args.skip_permissions:
        engine_args.append("--skip-permissions")
    if args.verify:
        engine_args.append("--verify")

    client = _arena_client_for_root(root)
    print(f"[bench] arena {client.base_url}")
    try:
        challenges = client.list_challenges()
    except FGError as exc:
        print(f"[bench] cannot list challenges: {exc}")
        return 1
    todo = [c for c in challenges if not c.get("is_completed")]
    print(f"[bench] {len(challenges)} challenges, {len(todo)} unfinished")

    if args.parallel > 1:
        return _bench_parallel(args, client, root, cli, engine_args, todo, deadline)

    rounds = 0
    while todo and (deadline is None or time.time() < deadline):
        rounds += 1
        progressed = False
        for ch in list(todo):
            if deadline is not None and time.time() >= deadline:
                print("[bench] deadline reached")
                break
            code = str(ch.get("unique_code"))
            store = _bench_store(root, code)
            try:
                started = client.start_challenge(code)
            except FGError as exc:
                if "max active" in str(exc).lower():
                    print("[bench] active-container cap reached; closing the oldest and retrying next round")
                    break
                print(f"[bench] {code}: cannot start ({exc})")
                continue
            addrs = list(started.get("container_addr") or [])
            print(f"\n[bench] {code} started -> {addrs or '(no addr)'}")
            try:
                _bench_prepare_graph(store, ch, started, addrs)
            except Exception as exc:  # graph problems must not kill the run
                print(f"[bench] {code}: graph prep failed ({exc}); skipping this round")
                try:
                    client.close_challenge(code)
                except FGError:
                    pass
                continue
            try:
                cmd = cli + [
                    "--store", str(store.root), "auto",
                    "--minutes", str(args.minutes_per_challenge),
                    "--max-steps", str(args.max_steps),
                ] + engine_args
                subprocess.run(cmd, cwd=str(root / code), check=False)
                try:
                    _bench_submit_recorded(store, code)
                except Exception as exc:
                    print(f"[bench] {code}: flag submission failed ({exc}); "
                          f"flags stay recorded and will retry next round")
                # did we finish it?
                try:
                    fresh = {str(c.get("unique_code")): c for c in client.list_challenges()}
                    if fresh.get(code, {}).get("is_completed"):
                        print(f"[bench] {code} COMPLETE")
                except FGError:
                    pass
            finally:
                try:
                    client.close_challenge(code)
                    print(f"[bench] {code} closed")
                except FGError as exc:
                    print(f"[bench] {code} close failed (non-fatal): {exc}")
            progressed = True
        try:
            challenges = client.list_challenges()
        except FGError as exc:
            print(f"[bench] cannot refresh challenges: {exc}")
            break
        todo = [c for c in challenges if not c.get("is_completed")]
        if not progressed:
            print("[bench] no progress this round — stopping")
            break
        print(f"[bench] round {rounds}: {len(todo)} still unfinished")
        time.sleep(args.round_gap_seconds)

    done = len([c for c in challenges if c.get("is_completed")])
    print(f"[bench] finished: {done}/{len(challenges)} complete after {rounds} round(s)")
    return 0


def _bench_parallel(args, client, root, cli, engine_args, todo, deadline) -> int:
    """Parallel mode: keep up to --parallel per-challenge workers running.

    Each worker is an independent `ben auto` subprocess on its own graph;
    graphs are flock-guarded so concurrent workers never corrupt state. When a
    worker finishes, its recorded flags are submitted, completion checked, and
    the container closed — then a new challenge takes the freed slot (until
    the platform's active-container cap, which we honor by simply stopping
    backfill for a while).
    """
    limit = args.parallel
    print(f"[bench] parallel mode: up to {limit} workers "
          f"(deadline {datetime.fromtimestamp(deadline).strftime('%H:%M') if deadline else 'none'})")
    pending = list(todo)
    running: dict[str, tuple[subprocess.Popen, Store]] = {}
    done_flags = 0

    def _finish(code: str) -> None:
        nonlocal done_flags
        proc, store = running.pop(code)
        try:
            done_flags += _bench_submit_recorded(store, code)
        except Exception as exc:
            print(f"[bench] {code}: flag submission failed ({exc}); retry next round")
        try:
            fresh = {str(c.get("unique_code")): c for c in client.list_challenges()}
            if fresh.get(code, {}).get("is_completed"):
                print(f"[bench] {code} COMPLETE")
        except FGError:
            pass
        try:
            client.close_challenge(code)
            print(f"[bench] {code} closed")
        except FGError as exc:
            print(f"[bench] {code} close failed (non-fatal): {exc}")

    while (pending or running) and (deadline is None or time.time() < deadline):
        # backfill free slots
        while pending and len(running) < limit:
            if deadline is not None and time.time() >= deadline:
                break
            ch = pending.pop(0)
            code = str(ch.get("unique_code"))
            try:
                started = client.start_challenge(code)
            except FGError as exc:
                if "max active" in str(exc).lower():
                    pending.insert(0, ch)  # try again after a slot frees
                    print("[bench] platform active-container cap reached; waiting for a slot")
                    break
                print(f"[bench] {code}: cannot start ({exc}); will retry next round")
                pending.append(ch)
                break
            addrs = list(started.get("container_addr") or [])
            print(f"[bench] {code} started -> {addrs or '(no addr)'} (workers: {len(running) + 1}/{limit})")
            store = _bench_store(root, code)
            try:
                _bench_prepare_graph(store, ch, started, addrs)
            except Exception as exc:
                print(f"[bench] {code}: graph prep failed ({exc}); skipping")
                try:
                    client.close_challenge(code)
                except FGError:
                    pass
                continue
            cmd = cli + [
                "--store", str(store.root), "auto",
                "--minutes", str(args.minutes_per_challenge),
                "--max-steps", str(args.max_steps),
            ] + engine_args
            proc = subprocess.Popen(cmd, cwd=str(root / code),
                                    stdout=sys.stdout, stderr=sys.stderr)
            running[code] = (proc, store)
            time.sleep(2)  # stagger starts against API bursts

        # reap finished workers
        for code in list(running):
            if running[code][0].poll() is not None:
                _finish(code)
        if running:
            time.sleep(args.poll_seconds or 5)
        elif pending:
            time.sleep(5)  # cap reached and nothing running: brief wait

    # deadline: submit whatever the still-running workers already recorded
    for code in list(running):
        running[code][0].terminate()
    for code in list(running):
        _finish(code)

    try:
        challenges = client.list_challenges()
    except FGError:
        challenges = []
    done = len([c for c in challenges if c.get("is_completed")])
    print(f"[bench] finished: {done}/{len(challenges)} complete, "
          f"{done_flags} flag submission(s) accepted")
    return 0


def _arena_client_for_root(root: Path):
    """Arena client for bench: look for arena.json in <root>/.ben or the cwd,
    else fall back to env vars."""
    for candidate in (root / ".ben", Path(".ben")):
        if (candidate / "arena.json").exists():
            return _arena_client(Store(candidate))
    return _arena_client(Store(root / ".ben"))
