"""sweep/show/doc/recall commands and editor helpers."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from ben import config
from ben.core.timebudget import deadline_from_args, format_time_budget
from ben.consts import GOAL_ID
from ben.core.errors import FGError
from ben.core.io import read_json
from ben.core.recall import recall
from ben.core.schema import _validate_lookup_id
from ben.core.store import Store
from ben.agents.prompt import render_recall


def cmd_sweep(args) -> int:
    """Drive multiple per-challenge graphs in rotation until deadline.

    Layout: one directory per challenge, each with its own .ben/ graph:

        runs/
        ├── c01/.ben/project.json   goal: capture flag for challenge c01
        ├── c02/.ben/project.json
        └── ...

    Each round gives every unfinished challenge `--minutes-per` of autonomous
    work (reason -> explore -> ... via `ben auto`). Stops when the global
    deadline passes or every graph reaches its goal.
    """
    root = Path(args.root)
    if not root.is_dir():
        raise FGError(f"sweep root {root} is not a directory")
    graph_dirs = sorted(
        p.parent for p in root.glob("*/.ben/project.json")
    )
    if not graph_dirs:
        raise FGError(f"no */.ben/project.json found under {root}")
    deadline = deadline_from_args(args)
    if deadline is None:
        raise FGError("sweep needs --minutes or --deadline (the match slot clock)")
    if args.minutes_per < 1:
        raise FGError("--minutes-per must be at least 1")

    cli = [sys.executable, str(Path(__file__).resolve()), "auto"]
    passthrough = ["--model", args.model]
    if args.skip_permissions:
        passthrough.append("--skip-permissions")
    if args.verify:
        passthrough.append("--verify")
    if args.templates:
        passthrough.extend(["--templates", args.templates])

    print(f"[sweep] {len(graph_dirs)} challenge graph(s) under {root}")
    print(f"[sweep] deadline {datetime.fromtimestamp(deadline).strftime('%H:%M')} "
          f"({format_time_budget(deadline)})")
    while time.time() < deadline:
        pending = []
        for d in graph_dirs:
            try:
                status = (read_json(d / ".ben" / "project.json")).get("status")
            except (json.JSONDecodeError, OSError):
                status = "active"  # unreadable -> still try to work it
            if status != "completed":
                pending.append(d)
        if not pending:
            print("[sweep] all challenge graphs completed")
            break
        for d in pending:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            budget = min(args.minutes_per, max(1, int(remaining // 60)))
            print(f"\n[sweep] {d.name}: auto for {budget}m "
                  f"({len(pending)} pending, {format_time_budget(deadline)})")
            cmd = cli + [
                "--store", str(d / ".ben"), "auto",
                "--minutes", str(budget),
                "--max-steps", str(args.max_steps),
            ] + passthrough
            subprocess.run(cmd, cwd=str(d), check=False)

    done = 0
    for d in graph_dirs:
        try:
            status = (read_json(d / ".ben" / "project.json")).get("status")
        except (json.JSONDecodeError, OSError):
            status = "?"
        mark = "DONE" if status == "completed" else status
        print(f"[sweep] {d.name}: {mark}")
        done += 1 if status == "completed" else 0
    print(f"[sweep] finished: {done}/{len(graph_dirs)} goals reached")
    return 0


def cmd_show(args) -> int:
    store = Store(Path(args.store))
    store.require()
    if args.entity == "project":
        print(json.dumps(store.load_project(), ensure_ascii=False, indent=2))
        return 0
    if not args.id:
        raise FGError(f"show {args.entity} requires an id")
    if args.entity == "fact":
        print(json.dumps(store.get_fact(args.id), ensure_ascii=False, indent=2))
    elif args.entity == "intent":
        print(json.dumps(store.get_intent(args.id), ensure_ascii=False, indent=2))
    return 0


def cmd_doc(args) -> int:
    """Read or write a node's detailed document (the third doc layer).
    `ben doc f001` prints the doc; `ben doc f001 --set '<text>'` /
    `--set-file <path>` writes it. Pass --edit to open $EDITOR."""
    store = Store(Path(args.store))
    store.require()
    _validate_lookup_id(args.id, "node")
    # Resolve the node (fact or intent) without ever accepting a path-like id.
    if args.id == GOAL_ID or (store.facts_dir / f"{args.id}.json").exists():
        node = store.get_fact(args.id)
    elif (store.intents_dir / f"{args.id}.json").exists():
        node = store.get_intent(args.id)
    else:
        raise FGError(f"no fact or intent named {args.id}")

    # WRITE paths
    if args.set is not None or args.set_file or args.edit:
        expected_doc = node.get("doc")
        if args.edit:
            new_doc = _edit_via_editor(node.get("doc") or "", title=f"{args.id} doc")
        elif args.set_file:
            new_doc = Path(args.set_file).read_text(encoding="utf-8")
        else:
            new_doc = args.set
        new_doc = new_doc.strip() if isinstance(new_doc, str) else None
        node = store.update_doc(args.id, new_doc, expected_doc=expected_doc)
        print(f"updated doc for {args.id} ({len(node['doc'] or '')} chars)" if node["doc"]
              else f"cleared doc for {args.id}")
        return 0

    # READ path: print the doc (or note its absence)
    doc = node.get("doc")
    if doc:
        print(doc)
    else:
        sys.stderr.write(f"{args.id} has no doc. add one: ben doc {args.id} --set '...' or --edit\n")
        return 1
    return 0


def cmd_recall(args) -> int:
    """Find prior facts/intents whose title+description look similar to the
    given query. Use this BEFORE starting a new task: if a strong match
    exists, read its doc with `ben doc <id>` and reuse what was learned."""
    store = Store(Path(args.store))
    store.require()
    query = (args.query or "").strip()
    if not query:
        raise FGError("recall: query is required")
    if args.limit < 1:
        raise FGError("recall: --limit must be >= 1")
    kinds: tuple[str, ...]
    if args.kind == "fact":
        kinds = ("fact",)
    elif args.kind == "intent":
        kinds = ("intent",)
    else:
        kinds = ("fact", "intent")
    matches = recall(store, query, limit=args.limit, kinds=kinds)
    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
    else:
        print(render_recall(matches, query))
    return 0 if matches else 1


def _edit_via_editor(initial: str, title: str) -> str:
    import subprocess
    import tempfile
    editor = config.get("EDITOR") or config.get("VISUAL") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(initial)
        tmp = fh.name
    try:
        subprocess.run([editor, tmp], check=True)
        return Path(tmp).read_text(encoding="utf-8")
    finally:
        Path(tmp).unlink(missing_ok=True)
