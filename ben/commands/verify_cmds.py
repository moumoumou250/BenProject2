"""``ben verify`` — machine evidence for concluding intents (R-03 / R-11).

Distinct from:
- ``ben dispatch verify`` — LLM review of a concluded fact
- ``ben validate`` — graph schema / integrity only
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ben.core.evidence import (
    git_dirty,
    git_head_sha,
    run_check,
    verify_dir_for_store,
)
from ben.core.errors import FGError
from ben.core.store import Store
from ben.core.log import run_event


def _repo_root() -> Path:
    """BenProject checkout root (this file is ``ben/commands/verify_cmds.py``)."""
    return Path(__file__).resolve().parent.parent.parent


def _default_checks(repo: Path, *, with_run: bool) -> list[tuple[str, list[str]]]:
    py = sys.executable
    checks = [
        ("arch", [py, str(repo / "scripts" / "ci" / "arch_check.py")]),
        ("pytest", [py, "-m", "pytest", "-q", "--tb=no"]),
    ]
    if with_run:
        # Smoke: status/graph/dispatch dry-run against the active store via env
        # is caller-specific; here we only prove the CLI entrypoints import.
        checks.append(("smoke_status", [py, "-m", "ben", "status", "--help"]))
        checks.append(("smoke_graph", [py, "-m", "ben", "graph", "--help"]))
        checks.append((
            "smoke_dispatch",
            [py, "-m", "ben", "dispatch", "reason", "--help"],
        ))
    return checks


def cmd_verify(args) -> int:
    """Produce ``report.json`` (+ optional ``smoke.json``) under runs/.../verify/."""
    store = Store(Path(args.store))
    store.require()
    intent_id = args.intent
    if not intent_id:
        raise FGError("verify requires --intent <id>")
    # Intent must exist (may still be open — evidence is pre-done).
    store.get_intent(intent_id)

    repo = _repo_root()
    out_dir = verify_dir_for_store(store.root)
    cwd = Path.cwd()
    sha = git_head_sha(cwd)
    dirty = git_dirty(cwd)

    with_run = bool(getattr(args, "run", False))
    checks_out: list[dict] = []
    run_event("verify_start", intent=intent_id, sha=sha, run=with_run)

    for name, argv in _default_checks(repo, with_run=with_run):
        result = run_check(name, argv, cwd=cwd)
        checks_out.append(result)
        run_event("verify_check", intent=intent_id, name=name, exit=result["exit"])

    overall = 0 if all(c["exit"] == 0 for c in checks_out) else 1
    report = {
        "intent": intent_id,
        "sha": sha,
        "dirty": dirty,
        "checks": checks_out,
        "exit": overall,
        "path": str(out_dir / "report.json"),
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if with_run:
        smoke = {
            "argv": [c["cmd"] for c in checks_out if c["name"].startswith("smoke_")],
            "checks": [c for c in checks_out if c["name"].startswith("smoke_")],
            "exit": 0 if all(
                c["exit"] == 0 for c in checks_out if c["name"].startswith("smoke_")
            ) else 1,
        }
        (out_dir / "smoke.json").write_text(
            json.dumps(smoke, indent=2) + "\n", encoding="utf-8"
        )

    run_event("verify_end", intent=intent_id, exit=overall, path=str(report_path))
    print(str(report_path))
    if overall != 0:
        for c in checks_out:
            if c["exit"] != 0:
                print(f"  FAIL {c['name']} exit={c['exit']}: {c['tail'][:200]}", file=sys.stderr)
    return overall
