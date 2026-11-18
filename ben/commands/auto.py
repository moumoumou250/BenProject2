"""Autonomy loop with slot-clock time budgets."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from ben.agents.dispatch import (
    _dispatch_reason,
    dispatch_explore,
    dispatch_reason,
    dispatch_verify_llm,
)
from ben.core.errors import FGError
from ben.core.graph import build_graph_view, frontier
from ben.core.log import run_event
from ben.core.store import Store
from ben.core.timebudget import deadline_from_args, format_time_budget


def cmd_auto(args) -> int:
    """Drive the whole graph forward until goal reached or budget exhausted.

    One iteration = reason (propose/complete) ; then for each newly-ready
    intent: explore ; (optionally) verify. Stops on: goal complete, reason
    returns noop/rejected twice in a row, no progress, or step budget hit.
    """
    store = Store(Path(args.store))
    store.require()
    templates_dir = Path(args.templates)
    model = args.model
    timeout = args.timeout
    skip = args.skip_permissions
    cwd = Path.cwd()
    max_steps = args.max_steps
    max_explore = args.max_explore
    if timeout < 1:
        raise FGError("--timeout must be at least 1 second")
    if max_steps < 1:
        raise FGError("--max-steps must be at least 1")
    if max_explore < 1:
        raise FGError("--max-explore must be at least 1")
    verify = args.verify
    dry = args.dry_run
    deadline = deadline_from_args(args)
    if deadline is not None:
        print(f"[auto] deadline {datetime.fromtimestamp(deadline).strftime('%Y-%m-%d %H:%M')} "
              f"({format_time_budget(deadline)})")

    print(f"[auto] start  model={model} max_steps={max_steps} verify={verify}")
    noop_streak = 0
    reason_failures = 0  # transient API errors must not kill the loop
    explore_count = 0
    for step in range(1, max_steps + 1):
        if deadline is not None and time.time() >= deadline:
            print("[auto] deadline reached — stopping (record what you have)")
            break
        args.time_budget = format_time_budget(deadline)
        project = store.load_project()
        if project["status"] == "completed":
            print(f"[auto] step {step}: project already completed")
            break
        before = _graph_signature(store)

        # 1) reason
        print(f"[auto] step {step}.1 reason")
        if dry:
            # dry-run prints the rendered prompt; it never mutates the graph,
            # so one pass is enough instead of repeating max_steps times.
            _dispatch_reason(store, templates_dir, model, timeout, skip, cwd, args)
            break
        try:
            run_event("worker_step", step=step, phase="reason")
            kind, summary = _run_reason_raw(
                store, templates_dir, model, timeout, skip, cwd,
                time_budget=getattr(args, "time_budget", "") or "",
            )
            reason_failures = 0
        except FGError as exc:
            reason_failures += 1
            print(f"[auto] step {step}: reason failed ({reason_failures}): {exc}")
            if reason_failures >= 2:
                print("[auto] reason failed twice in a row — stopping this challenge (graph preserved)")
                break
            time.sleep(15)
            continue
        print(f"[auto]        reason -> {summary}")

        project = store.load_project()
        if project["status"] == "completed":
            print(f"[auto] step {step}: goal completed by reason")
            break
        # noop/rejected means "no new intents" — still explore the existing
        # frontier. Only stop after two consecutive noops with no ready work.
        if kind in ("noop", "rejected"):
            noop_streak += 1
        else:
            noop_streak = 0

        # 2) explore each ready intent, up to the per-step cap
        auto_worker = _worker_id(model)
        ready = [
            i for i in frontier(store)
            if not i.get("worker") or i.get("worker") == auto_worker
        ]
        if not ready:
            print(f"[auto] step {step}.2 no ready intents after reason")
            if kind in ("noop", "rejected") and noop_streak >= 2:
                print(f"[auto] step {step}: reason {kind} twice with empty frontier — stopping")
                break
            if _graph_signature(store) == before:
                print("[auto] no graph change and no ready work — stopping")
                break
            continue
        if kind in ("noop", "rejected"):
            print(f"[auto] step {step}.2 reason was {kind}; exploring {len(ready)} existing intent(s)")
        for intent in ready:
            if explore_count >= max_explore:
                print(f"[auto] explore cap ({max_explore}) reached this run")
                break
            if intent["requires_confirmation"] and not intent["confirmed_at"]:
                print(f"[auto] step {step}.2 skip {intent['id']} (needs confirmation)")
                continue
            print(f"[auto] step {step}.2 explore {intent['id']}")
            try:
                _run_explore_raw(
                    store, templates_dir, intent, model, timeout, skip, cwd,
                    claim=True,
                )
                explore_count += 1
                # Brief pause between explores to respect low RPM gateways.
                time.sleep(1.5)
            except FGError as exc:
                if "already concluded" in str(exc):
                    # the executor concluded the intent itself (`ben done`)
                    # — that is a success, not a failure
                    explore_count += 1
                    print(f"[auto]        {intent['id']} concluded by the executor itself")
                    continue
                # Failed explore must not leave a sticky claim that blocks the
                # next auto PID (worker id includes getpid()).
                try:
                    store.release_intent(intent["id"], auto_worker)
                except FGError:
                    pass
                print(f"[auto] explore {intent['id']} failed: {exc}")
                continue
            # 3) optional verify
            if verify:
                iid = intent["id"]
                refreshed = store.get_intent(iid)
                if refreshed["to"] is not None:
                    print(f"[auto] step {step}.3 verify {iid}")
                    try:
                        verified, issues = _run_verify_raw(
                            store, templates_dir, refreshed, model, timeout, skip, cwd
                        )
                        tag = "VERIFIED" if verified else "FAILED"
                        print(f"[auto]        verify {iid} -> {tag}" + (f": {issues}" if issues else ""))
                        if not verified:
                            store.add_hint(
                                content=(
                                    f"verification failed for {iid}: "
                                    f"{issues or 'the produced fact did not pass verification'}"
                                ),
                                creator="verify",
                            )
                    except FGError as exc:
                        print(f"[auto] verify {iid} failed: {exc}")
                        store.add_hint(
                            content=f"verification could not complete for {iid}: {exc}",
                            creator="verify",
                        )

        if _graph_signature(store) == before:
            print(f"[auto] step {step}: no graph change after work — stopping")
            break

    project = store.load_project()
    print(f"[auto] done  status={project['status']}  explored={explore_count}")
    return 0


def _run_reason_raw(store, templates_dir, model, timeout, skip, cwd, time_budget: str = "") -> tuple[str, str]:
    """Like _dispatch_reason but returns (kind, summary) instead of printing."""
    result = dispatch_reason(
        store, templates_dir, model, timeout, skip, cwd,
        time_budget=time_budget, dry_run=False,
    )
    return result.kind or "noop", result.summary


def _run_explore_raw(store, templates_dir, intent, model, timeout, skip, cwd, claim=False) -> dict:
    result = dispatch_explore(
        store, templates_dir, intent, model, timeout, skip, cwd,
        claim=claim, dry_run=False, warn_permissions=False,
    )
    if result.fact is not None:
        return result.fact
    return store.get_fact(intent["to"]) if intent.get("to") else {}


def _run_verify_raw(store, templates_dir, intent, model, timeout, skip, cwd) -> tuple[bool, str]:
    result = dispatch_verify_llm(
        store, templates_dir, intent, model, timeout, skip, cwd, dry_run=False,
    )
    return result.ok, result.issues or ""


def _graph_signature(store: Store) -> tuple:
    """Cheap snapshot to detect whether a step changed the graph."""
    g = build_graph_view(store)
    facts = tuple((f["id"], f["description"]) for f in g["facts"])
    intents = tuple(
        (i["id"], i["to"], i["confirmed_at"]) for i in g["intents"]
    )
    return (g["project"]["status"], facts, intents)
