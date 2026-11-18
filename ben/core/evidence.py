"""Machine evidence for concluding intents (R-03).

``ben verify`` (not ``ben dispatch verify``) writes a JSON report. Store-level
``conclude_with_new_fact`` accepts that report or ``force=True`` with a trail.

Naming:
- ``ben verify`` — run arch_check/pytest (and optional smoke), write report.json
- ``ben dispatch verify`` — LLM post-hoc review of an already-concluded intent
- ``ben validate`` — graph integrity only
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ben.core.errors import FGError
from ben.core.paths import ensure_output_dir


def git_head_sha(cwd: Path | None = None) -> str:
    """Return current HEAD sha, or 'nogit' when unavailable."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd or Path.cwd(),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return out.strip() or "nogit"
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def git_dirty(cwd: Path | None = None) -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=cwd or Path.cwd(),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return bool(out.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def verify_dir_for_store(store_root: Path) -> Path:
    """``<runtime>/verify/<ts>/`` next to the graph (via paths.output_dir)."""
    base = store_root.parent if store_root.name == ".ben" else store_root
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ensure_output_dir(base) / "verify" / ts
    out.mkdir(parents=True, exist_ok=True)
    return out


def load_evidence(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FGError(f"evidence report not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FGError(f"cannot read evidence {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise FGError(f"evidence {p} must be a JSON object")
    return data


def validate_evidence_for_intent(
    evidence: dict[str, Any],
    *,
    intent_id: str,
    expected_sha: str | None = None,
) -> None:
    """Four-condition gate from OPTIMIZATION-PLAN-v4 R-03."""
    if evidence.get("exit") != 0:
        raise FGError(
            f"evidence exit={evidence.get('exit')!r} (need 0); "
            "re-run `ben verify --intent ...` or pass --force"
        )
    if evidence.get("intent") != intent_id:
        raise FGError(
            f"evidence intent={evidence.get('intent')!r} does not match {intent_id}"
        )
    sha = evidence.get("sha")
    if expected_sha is None:
        expected_sha = git_head_sha()
    if sha != expected_sha:
        raise FGError(
            f"evidence sha={sha!r} does not match HEAD {expected_sha!r} "
            "(re-verify after commits, or --force)"
        )
    checks = evidence.get("checks")
    if not isinstance(checks, list) or not checks:
        raise FGError("evidence must include a non-empty checks list")
    for check in checks:
        if not isinstance(check, dict):
            raise FGError("evidence check entries must be objects")
        if check.get("exit") != 0:
            name = check.get("name", "?")
            raise FGError(f"evidence check {name!r} exit={check.get('exit')!r}")


def merge_evidence_into_data(
    data: dict[str, str] | None,
    evidence: dict[str, Any],
    *,
    forced: bool = False,
) -> dict[str, str]:
    out = dict(data or {})
    out["evidence"] = str(evidence.get("path") or evidence.get("report") or "")
    if evidence.get("sha"):
        out["sha"] = str(evidence["sha"])
    if evidence.get("model"):
        out["model"] = str(evidence["model"])
    if forced:
        out["forced"] = "true"
    return out


def run_check(
    name: str,
    argv: list[str],
    *,
    cwd: Path,
    timeout: int = 600,
) -> dict[str, Any]:
    """Run one check command; return {name, cmd, exit, tail}."""
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        blob = (proc.stdout or "") + (proc.stderr or "")
        tail = "\n".join(blob.strip().splitlines()[-8:]) if blob.strip() else ""
        return {
            "name": name,
            "cmd": " ".join(argv),
            "exit": int(proc.returncode),
            "tail": tail[:2000],
        }
    except subprocess.TimeoutExpired:
        return {"name": name, "cmd": " ".join(argv), "exit": 124, "tail": "timeout"}
    except OSError as exc:
        return {"name": name, "cmd": " ".join(argv), "exit": 127, "tail": str(exc)}
